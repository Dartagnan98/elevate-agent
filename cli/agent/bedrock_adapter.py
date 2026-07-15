"""AWS Bedrock Converse API adapter for Elevate Agent.

Provides native integration with Amazon Bedrock using the Converse API,
bypassing the OpenAI-compatible endpoint in favor of direct AWS SDK calls.
This enables full access to the Bedrock ecosystem:

  - **Native Converse API**: Unified interface for all Bedrock models
    (Claude, Nova, Llama, Mistral, etc.) with streaming support.
  - **AWS credential chain**: IAM roles, SSO profiles, environment variables,
    instance metadata — zero API key management for AWS-native environments.
  - **Dynamic model discovery**: Auto-discovers available foundation models
    and cross-region inference profiles via the Bedrock control plane.
  - **Guardrails support**: Optional Bedrock Guardrails configuration for
    content filtering and safety policies.
  - **Inference profiles**: Supports cross-region inference profiles
    (us.anthropic.claude-*, global.anthropic.claude-*) for better capacity
    and automatic failover.

Architecture follows the same pattern as ``anthropic_adapter.py``:
  - All Bedrock-specific logic is isolated in this module.
  - Messages/tools are converted between OpenAI format and Converse format.
  - Responses are normalized back to OpenAI-compatible objects for the agent loop.

Reference: OpenClaw's ``extensions/amazon-bedrock/`` plugin, which implements
the same Converse API integration in TypeScript via ``@aws-sdk/client-bedrock``.

Requires: ``boto3`` (optional dependency — only needed when using the Bedrock provider).
"""

import base64
import binascii
import json
import logging
import math
import os
import re
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ensure boto3/botocore are installed before any code in this module runs.
# Upstream removed boto3 from [all] extras (PRs #24220, #24515); lazy_deps
# handles on-demand installation so the Bedrock provider still works in the
# EKS deployment without baking boto3 into the base image.
# ---------------------------------------------------------------------------
try:
    from tools.lazy_deps import ensure
    ensure("provider.bedrock", prompt=False)
except Exception:
    pass  # lazy_deps unavailable or install failed — let downstream imports surface the real error


# ---------------------------------------------------------------------------
# Lazy boto3 import — only loaded when the Bedrock provider is actually used.
# This keeps startup fast for users who don't use Bedrock.
# ---------------------------------------------------------------------------

_bedrock_runtime_client_cache: Dict[Any, Any] = {}
_bedrock_control_client_cache: Dict[str, Any] = {}
_bedrock_runtime_client_cache_lock = threading.Lock()


def _require_boto3():
    """Import boto3, raising a clear error if not installed."""
    try:
        import boto3
        return boto3
    except ImportError:
        raise ImportError(
            "The 'boto3' package is required for the AWS Bedrock provider. "
            "Install it with: pip install boto3\n"
            "Or install Elevate with Bedrock support: pip install -e '.[bedrock]'"
        )


def _normalize_runtime_timeout(timeout: Optional[float]) -> Optional[float]:
    """Normalize one botocore connect/read timeout policy."""
    if timeout is None:
        return None
    if isinstance(timeout, bool):
        raise ValueError("Bedrock timeout must be a positive number")
    try:
        normalized = float(timeout)
    except (TypeError, ValueError) as exc:
        raise ValueError("Bedrock timeout must be a positive number") from exc
    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError("Bedrock timeout must be a positive number")
    return normalized


_BEDROCK_RUNTIME_ENDPOINT_RE = re.compile(
    r"^bedrock-runtime(?:-fips)?\.([a-z0-9-]+)\.amazonaws\.com(?:\.cn)?$"
)


def normalize_bedrock_runtime_endpoint(endpoint_url: Any, region: str) -> str:
    """Validate and canonicalize an explicit AWS Bedrock Runtime endpoint.

    Bedrock clients use the default AWS credential chain.  Passing an arbitrary
    ``endpoint_url`` would therefore be a credential-exfiltration primitive, so
    only exact HTTPS AWS Runtime origins are accepted and the hostname's region
    must agree with the client region.
    """
    raw_endpoint = str(endpoint_url or "").strip()
    normalized_region = str(region or "").strip()
    if not raw_endpoint:
        raise ValueError("Bedrock endpoint URL cannot be empty")
    if not normalized_region:
        raise ValueError("Bedrock endpoint region cannot be empty")

    try:
        parsed = urlsplit(raw_endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Bedrock endpoint URL is malformed") from exc
    hostname = (parsed.hostname or "").lower()
    match = _BEDROCK_RUNTIME_ENDPOINT_RE.fullmatch(hostname)
    if (
        parsed.scheme.lower() != "https"
        or not match
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Bedrock endpoint URL must be an exact HTTPS AWS Runtime origin"
        )
    if match.group(1) != normalized_region:
        raise ValueError(
            "Bedrock endpoint region does not match the configured AWS region"
        )
    return f"https://{hostname}"


def _runtime_client_cache_key(
    region: str,
    timeout: Optional[float],
    endpoint_url: Optional[str] = None,
) -> Any:
    """Key clients by exact region, timeout, and explicit endpoint policy."""
    normalized_timeout = _normalize_runtime_timeout(timeout)
    normalized_endpoint = (
        normalize_bedrock_runtime_endpoint(endpoint_url, region)
        if endpoint_url
        else None
    )
    if normalized_timeout is None and normalized_endpoint is None:
        return region
    if normalized_endpoint is None:
        return (region, normalized_timeout)
    return (region, normalized_timeout, normalized_endpoint)


def _create_bedrock_runtime_client(
    region: str,
    timeout: Optional[float] = None,
    endpoint_url: Optional[str] = None,
):
    """Create one validated ``bedrock-runtime`` client."""
    boto3 = _require_boto3()
    client_kwargs: Dict[str, Any] = {"region_name": region}
    normalized_timeout = _normalize_runtime_timeout(timeout)
    normalized_endpoint = (
        normalize_bedrock_runtime_endpoint(endpoint_url, region)
        if endpoint_url
        else None
    )
    if normalized_endpoint is not None:
        client_kwargs["endpoint_url"] = normalized_endpoint
    if normalized_timeout is not None:
        from botocore.config import Config

        client_kwargs["config"] = Config(
            connect_timeout=normalized_timeout,
            read_timeout=normalized_timeout,
            retries={"total_max_attempts": 1},
        )
    return boto3.client("bedrock-runtime", **client_kwargs)


def _get_bedrock_runtime_client(
    region: str,
    timeout: Optional[float] = None,
    endpoint_url: Optional[str] = None,
    *,
    exclusive: bool = False,
):
    """Get or create a ``bedrock-runtime`` client for the given policy.

    Uses the default AWS credential chain (env vars → profile → instance role).
    Clients are cached by exact region, timeout, and explicit endpoint policy.
    Timeout-bearing clients disable botocore retries so configured deadlines
    remain bounded.  Explicit endpoints are restricted to trusted AWS Runtime
    origins before boto3 can receive credentials.  Main turn calls request an
    exclusive client so timeout/interrupt cancellation cannot close a client
    concurrently used by another session; auxiliary calls retain caching.
    """
    if exclusive:
        return _create_bedrock_runtime_client(
            region,
            timeout=timeout,
            endpoint_url=endpoint_url,
        )
    cache_key = _runtime_client_cache_key(region, timeout, endpoint_url)
    with _bedrock_runtime_client_cache_lock:
        if cache_key not in _bedrock_runtime_client_cache:
            _bedrock_runtime_client_cache[cache_key] = (
                _create_bedrock_runtime_client(
                    region,
                    timeout=timeout,
                    endpoint_url=endpoint_url,
                )
            )
        return _bedrock_runtime_client_cache[cache_key]


def _get_bedrock_control_client(region: str):
    """Get or create a cached ``bedrock`` control-plane client for model discovery."""
    if region not in _bedrock_control_client_cache:
        boto3 = _require_boto3()
        _bedrock_control_client_cache[region] = boto3.client(
            "bedrock", region_name=region,
        )
    return _bedrock_control_client_cache[region]


def reset_client_cache():
    """Clear cached boto3 clients. Used in tests and profile switches."""
    with _bedrock_runtime_client_cache_lock:
        _bedrock_runtime_client_cache.clear()
    _bedrock_control_client_cache.clear()


def invalidate_runtime_client(
    region: str,
    timeout: Optional[float] = None,
    *,
    endpoint_url: Optional[str] = None,
    expected_client: Any = None,
) -> bool:
    """Evict the cached ``bedrock-runtime`` client for a single region.

    With ``timeout`` or an explicit endpoint, only the exact policy is removed.
    With neither, every policy for the region is removed for legacy callers.
    When ``expected_client`` is supplied, eviction is compare-and-pop:
    a late failure from an old request cannot evict a fresh replacement that
    another request already installed under the same cache key.

    Returns True if at least one cached entry was evicted.
    """
    if timeout is not None or endpoint_url:
        key = _runtime_client_cache_key(region, timeout, endpoint_url)
        with _bedrock_runtime_client_cache_lock:
            current = _bedrock_runtime_client_cache.get(key)
            if current is None:
                return False
            if expected_client is not None and current is not expected_client:
                return False
            _bedrock_runtime_client_cache.pop(key, None)
            return True

    with _bedrock_runtime_client_cache_lock:
        stale_keys = [
            key
            for key, cached_client in _bedrock_runtime_client_cache.items()
            if key == region or (isinstance(key, tuple) and key and key[0] == region)
            if expected_client is None or cached_client is expected_client
        ]
        for key in stale_keys:
            _bedrock_runtime_client_cache.pop(key, None)
        return bool(stale_keys)


_GUARDRAIL_TRACE_VALUES = {"enabled", "disabled", "enabled_full"}
_GUARDRAIL_STREAM_MODES = {"sync", "async"}
_BEDROCK_GUARDRAIL_FIELDS = {
    "guardrail_identifier",
    "guardrailIdentifier",
    "guardrail_version",
    "guardrailVersion",
    "stream_processing_mode",
    "streamProcessingMode",
    "trace",
}


def _guardrail_alias_value(
    value: Dict[str, Any],
    snake_name: str,
    camel_name: str,
) -> str:
    """Read one snake/camel alias and reject conflicting policy values."""
    candidates = {
        str(value.get(name) or "").strip()
        for name in (snake_name, camel_name)
        if name in value and str(value.get(name) or "").strip()
    }
    if len(candidates) > 1:
        raise ValueError(
            "Conflicting Bedrock guardrail configuration values for "
            f"{snake_name} and {camel_name}"
        )
    return next(iter(candidates), "")


def normalize_bedrock_guardrail_config(
    value: Any,
    *,
    allow_disabled_options: bool = False,
) -> Optional[Dict[str, str]]:
    """Normalize one strict guardrail policy for every Bedrock surface.

    Both config-file snake_case and AWS SDK camelCase spellings are accepted.
    Unknown fields, conflicting aliases, partial identity, and invalid option
    values fail closed instead of silently weakening the configured policy.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Bedrock guardrail configuration must be a mapping")
    if not value:
        return None
    unknown_fields = set(value) - _BEDROCK_GUARDRAIL_FIELDS
    if unknown_fields:
        raise ValueError(
            "Unsupported Bedrock guardrail configuration fields: "
            + ", ".join(sorted(str(field) for field in unknown_fields))
        )

    identifier = _guardrail_alias_value(
        value, "guardrail_identifier", "guardrailIdentifier"
    )
    version = _guardrail_alias_value(
        value, "guardrail_version", "guardrailVersion"
    )
    if not identifier and not version:
        if allow_disabled_options:
            disabled_policy = True
        else:
            raise ValueError(
                "Bedrock guardrail configuration requires both an identifier and version"
            )
    else:
        disabled_policy = False
    if bool(identifier) != bool(version):
        raise ValueError(
            "Bedrock guardrail configuration requires both an identifier and version"
        )

    normalized: Dict[str, str] = {
        "guardrailIdentifier": identifier,
        "guardrailVersion": version,
    }
    stream_mode = _guardrail_alias_value(
        value, "stream_processing_mode", "streamProcessingMode"
    ).lower()
    if stream_mode:
        if stream_mode not in _GUARDRAIL_STREAM_MODES:
            raise ValueError(
                "Bedrock guardrail streamProcessingMode must be 'sync' or 'async'"
            )
        normalized["streamProcessingMode"] = stream_mode
    trace = str(value.get("trace") or "").strip().lower()
    if trace:
        if trace not in _GUARDRAIL_TRACE_VALUES:
            raise ValueError(
                "Bedrock guardrail trace must be enabled, disabled, or enabled_full"
            )
        normalized["trace"] = trace
    return None if disabled_policy else normalized


def prepare_converse_guardrail_config(
    guardrail_config: Optional[Dict[str, Any]],
    *,
    streaming: bool,
) -> Optional[Dict[str, str]]:
    """Validate guardrail policy and shape it for Converse or ConverseStream.

    ``streamProcessingMode`` exists only on ConverseStream's input shape.
    Keeping it on a non-streaming ``client.converse`` request causes local
    botocore parameter validation to fail before Bedrock can enforce the
    guardrail, so non-streaming callers deliberately omit that stream-only
    field while retaining identifier, version, and trace.
    """
    normalized = normalize_bedrock_guardrail_config(guardrail_config)
    if normalized is None:
        return None
    if not streaming:
        normalized.pop("streamProcessingMode", None)
    return normalized


def build_invoke_model_guardrail_headers(
    guardrail_config: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """Translate a Bedrock guardrail policy to InvokeModel request headers."""
    normalized = prepare_converse_guardrail_config(
        guardrail_config,
        streaming=False,
    )
    if not normalized:
        return {}
    headers = {
        "X-Amzn-Bedrock-GuardrailIdentifier": normalized["guardrailIdentifier"],
        "X-Amzn-Bedrock-GuardrailVersion": normalized["guardrailVersion"],
    }
    if normalized.get("trace"):
        # InvokeModel uses the uppercase enum; Converse uses lowercase.
        headers["X-Amzn-Bedrock-Trace"] = normalized["trace"].upper()
    return headers


# ---------------------------------------------------------------------------
# Stale-connection detection
# ---------------------------------------------------------------------------
#
# boto3 caches its HTTPS connection pool inside the client object. When a
# pooled connection is killed out from under us (NAT timeout, VPN flap,
# server-side TCP RST, proxy idle cull, etc.), the next use surfaces as
# one of a handful of low-level exceptions — most commonly
# ``botocore.exceptions.ConnectionClosedError`` or
# ``urllib3.exceptions.ProtocolError``. urllib3 also trips an internal
# ``assert`` in a couple of paths (connection pool state checks, chunked
# response readers) which bubbles up as a bare ``AssertionError`` with an
# empty ``str(exc)``.
#
# In all of these cases the client is the problem, not the request: retrying
# with the same cached client reproduces the failure until the process
# restarts. The fix is to evict the region's cached client so the next
# attempt builds a new one.

_STALE_LIB_MODULE_PREFIXES = (
    "urllib3.",
    "botocore.",
    "boto3.",
)


def _traceback_frames_modules(exc: BaseException):
    """Yield ``__name__``-style module strings for each frame in exc's traceback."""
    tb = getattr(exc, "__traceback__", None)
    while tb is not None:
        frame = tb.tb_frame
        module = frame.f_globals.get("__name__", "")
        yield module or ""
        tb = tb.tb_next


def is_stale_connection_error(exc: BaseException) -> bool:
    """Return True if ``exc`` indicates a dead/stale Bedrock HTTP connection.

    Matches:
      * ``botocore.exceptions.ConnectionError`` and subclasses
        (``ConnectionClosedError``, ``EndpointConnectionError``,
        ``ReadTimeoutError``, ``ConnectTimeoutError``).
      * ``urllib3.exceptions.ProtocolError`` / ``NewConnectionError`` /
        ``ConnectionError`` (best-effort import — urllib3 is a transitive
        dependency of botocore so it is always available in practice).
      * Bare ``AssertionError`` raised from a frame inside urllib3, botocore,
        or boto3. These are internal-invariant failures (typically triggered
        by corrupted connection-pool state after a dropped socket) and are
        recoverable by swapping the client.

    Non-library ``AssertionError``s (from application code or tests) are
    intentionally not matched — only library-internal asserts signal stale
    connection state.
    """
    # botocore: the canonical signal — HTTPClientError is the umbrella for
    # ConnectionClosedError, ReadTimeoutError, EndpointConnectionError,
    # ConnectTimeoutError, and ProxyConnectionError. ConnectionError covers
    # the same family via a different branch of the hierarchy.
    try:
        from botocore.exceptions import (
            ConnectionError as BotoConnectionError,
            HTTPClientError,
        )
        botocore_errors: tuple = (BotoConnectionError, HTTPClientError)
    except ImportError:  # pragma: no cover — botocore always present with boto3
        botocore_errors = ()
    if botocore_errors and isinstance(exc, botocore_errors):
        return True

    # urllib3: low-level transport failures
    try:
        from urllib3.exceptions import (
            ProtocolError,
            NewConnectionError,
            ConnectionError as Urllib3ConnectionError,
        )
        urllib3_errors = (ProtocolError, NewConnectionError, Urllib3ConnectionError)
    except ImportError:  # pragma: no cover
        urllib3_errors = ()
    if urllib3_errors and isinstance(exc, urllib3_errors):
        return True

    # Library-internal AssertionError (urllib3 / botocore / boto3)
    if isinstance(exc, AssertionError):
        for module in _traceback_frames_modules(exc):
            if any(module.startswith(prefix) for prefix in _STALE_LIB_MODULE_PREFIXES):
                return True

    return False


# ---------------------------------------------------------------------------
# AWS credential detection
# ---------------------------------------------------------------------------

# Priority order matches OpenClaw's resolveAwsSdkEnvVarName():
#   1. AWS_BEARER_TOKEN_BEDROCK (Bedrock-specific bearer token)
#   2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (explicit IAM credentials)
#   3. AWS_PROFILE (named profile → SSO, assume-role, etc.)
#   4. Implicit: instance role, ECS task role, Lambda execution role
_AWS_CREDENTIAL_ENV_VARS = [
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_PROFILE",
    # These are checked by boto3's default chain but we list them for
    # has_aws_credentials() detection:
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
]


def resolve_aws_auth_env_var(env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Return the name of the AWS auth source that is active, or None.

    Checks environment variables first, then falls back to boto3's credential
    chain for implicit sources (EC2 IMDS, ECS task role, etc.).

    This mirrors OpenClaw's ``resolveAwsSdkEnvVarName()`` — used to detect
    whether the user has any AWS credentials configured without actually
    attempting to authenticate.
    """
    env = env if env is not None else os.environ
    # Bearer token takes highest priority
    if env.get("AWS_BEARER_TOKEN_BEDROCK", "").strip():
        return "AWS_BEARER_TOKEN_BEDROCK"
    # Explicit access key pair
    if (env.get("AWS_ACCESS_KEY_ID", "").strip()
            and env.get("AWS_SECRET_ACCESS_KEY", "").strip()):
        return "AWS_ACCESS_KEY_ID"
    # Named profile (SSO, assume-role, etc.)
    if env.get("AWS_PROFILE", "").strip():
        return "AWS_PROFILE"
    # Container credentials (ECS, CodeBuild)
    if env.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip():
        return "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
    # Web identity (EKS IRSA)
    if env.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip():
        return "AWS_WEB_IDENTITY_TOKEN_FILE"
    # No env vars — check if boto3 can resolve credentials via IMDS or other
    # implicit sources (EC2 instance role, ECS task role, Lambda, etc.)
    try:
        import botocore.session
        session = botocore.session.get_session()
        credentials = session.get_credentials()
        if credentials is not None:
            resolved = credentials.get_frozen_credentials()
            if resolved and resolved.access_key:
                return "iam-role"
    except Exception:
        pass
    return None


def has_aws_credentials(env: Optional[Dict[str, str]] = None) -> bool:
    """Return True if any AWS credential source is detected.

    Checks environment variables first (fast, no I/O), then falls back to
    boto3's credential chain which covers EC2 instance roles, ECS task roles,
    Lambda execution roles, and other IMDS-based sources that don't set
    environment variables.

    This two-tier approach mirrors the pattern from OpenClaw PR #62673:
    cloud environments (EC2, ECS, Lambda) provide credentials via instance
    metadata, not environment variables. The env-var check is a fast path
    for local development; the boto3 fallback covers all cloud deployments.
    """
    if resolve_aws_auth_env_var(env) is not None:
        return True
    # Fall back to boto3's credential resolver — this covers EC2 instance
    # metadata (IMDS), ECS container credentials, and other implicit sources
    # that don't set environment variables.
    try:
        import botocore.session
        session = botocore.session.get_session()
        credentials = session.get_credentials()
        if credentials is not None:
            resolved = credentials.get_frozen_credentials()
            if resolved and resolved.access_key:
                return True
    except Exception:
        pass
    return False


def resolve_bedrock_region(env: Optional[Dict[str, str]] = None) -> str:
    """Resolve the AWS region for Bedrock API calls.

    Priority:
      1. AWS_REGION env var
      2. AWS_DEFAULT_REGION env var
      3. boto3/botocore configured region (from ~/.aws/config or SSO profile)
      4. us-east-1 (hard fallback)

    The boto3 fallback is critical for EU/AP users who configure their region
    in ~/.aws/config via a named profile rather than env vars — without it,
    live model discovery would always return us.* profile IDs regardless of
    the user's actual region.
    """
    env = env if env is not None else os.environ
    explicit = (
        env.get("AWS_REGION", "").strip()
        or env.get("AWS_DEFAULT_REGION", "").strip()
    )
    if explicit:
        return explicit
    try:
        import botocore.session
        region = botocore.session.get_session().get_config_variable("region")
        if region:
            return region
    except Exception:
        pass
    return "us-east-1"


def bedrock_model_ids_or_none() -> Optional[List[str]]:
    """Live-discover Bedrock model IDs for the active region.

    Returns a list of model ID strings if discovery succeeds and yields
    at least one model, or ``None`` on failure / empty result.  Callers
    should fall back to the static curated list when ``None`` is returned.

    This helper consolidates the discover → extract-ids → fallback
    pattern that was previously duplicated across ``provider_model_ids``,
    ``list_authenticated_providers`` section 2, and section 3.
    """
    try:
        discovered = discover_bedrock_models(resolve_bedrock_region())
        if discovered:
            return [m["id"] for m in discovered]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Tool-calling capability detection
# ---------------------------------------------------------------------------
# Some Bedrock models don't support tool/function calling. Sending toolConfig
# to these models causes ValidationException. We maintain a denylist of known
# non-tool-calling model patterns and strip tools for them.
#
# This is a conservative approach: unknown models are assumed to support tools.
# If a model fails with a tool-related ValidationException, add it here.

_NON_TOOL_CALLING_PATTERNS = [
    "deepseek.r1",          # DeepSeek R1 — reasoning only, no tool support
    "deepseek-r1",          # Alternate ID format
    "stability.",           # Image generation models
    "cohere.embed",         # Embedding models
    "amazon.titan-embed",   # Embedding models
]


def _model_supports_tool_use(model_id: str) -> bool:
    """Return True if the model is expected to support tool/function calling.

    Models in the denylist are known to reject toolConfig in the Converse API.
    Unknown models default to True (assume tool support).
    """
    model_lower = model_id.lower()
    return not any(pattern in model_lower for pattern in _NON_TOOL_CALLING_PATTERNS)


def is_anthropic_bedrock_model(model_id: str) -> bool:
    """Return True if the model is an Anthropic Claude model on Bedrock.

    These models should use the AnthropicBedrock SDK path for full feature
    parity (prompt caching, thinking budgets, adaptive thinking).
    Non-Claude models use the Converse API path.

    Matches:
      - ``anthropic.claude-*`` (foundation model IDs)
      - ``us.anthropic.claude-*`` (US inference profiles)
      - ``global.anthropic.claude-*`` (global inference profiles)
      - ``eu.anthropic.claude-*`` (EU inference profiles)
      - ``apac.anthropic.claude-*`` (Asia Pacific inference profiles)
      - Recognizable ``foundation-model/`` and ``inference-profile/`` ARNs

    Application inference-profile ARNs contain an opaque profile ID rather
    than the underlying foundation model.  They intentionally return False
    and use Converse, which is the only protocol we can select truthfully
    without a control-plane lookup.
    """
    model_lower = str(model_id or "").strip().lower()
    if model_lower.startswith("arn:"):
        arn_parts = model_lower.split(":", 5)
        if len(arn_parts) != 6:
            return False
        resource = arn_parts[5]
        for resource_prefix in ("foundation-model/", "inference-profile/"):
            if resource.startswith(resource_prefix):
                model_lower = resource[len(resource_prefix):]
                break
        else:
            return False

    # Strip regional prefix if present
    for prefix in ("us.", "global.", "eu.", "ap.", "apac.", "jp."):
        if model_lower.startswith(prefix):
            model_lower = model_lower[len(prefix):]
            break
    return model_lower.startswith("anthropic.claude")


# ---------------------------------------------------------------------------
# Message format conversion: OpenAI → Bedrock Converse
# ---------------------------------------------------------------------------

def convert_tools_to_converse(tools: List[Dict]) -> List[Dict]:
    """Convert OpenAI-format tool definitions to Bedrock Converse ``toolConfig``.

    OpenAI format::

        {"type": "function", "function": {"name": "...", "description": "...",
         "parameters": {"type": "object", "properties": {...}}}}

    Converse format::

        {"toolSpec": {"name": "...", "description": "...",
         "inputSchema": {"json": {"type": "object", "properties": {...}}}}}
    """
    if not tools:
        return []
    result = []
    for t in tools:
        fn = t.get("function", {})
        name = fn.get("name", "")
        description = fn.get("description", "")
        parameters = fn.get("parameters", {"type": "object", "properties": {}})
        result.append({
            "toolSpec": {
                "name": name,
                "description": description,
                "inputSchema": {"json": parameters},
            }
        })
    return result


def _decode_image_data_url(url: str) -> bytes:
    """Decode one base64 image data URL to the raw bytes botocore expects."""
    header, separator, encoded = str(url or "").partition(",")
    header_lower = header.lower()
    if (
        not separator
        or not header_lower.startswith("data:image/")
        or ";base64" not in header_lower
    ):
        raise ValueError("Bedrock image input must be a base64 image data URL")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Bedrock image data URL contains invalid base64") from exc


def _convert_content_to_converse(content) -> List[Dict]:
    """Convert OpenAI message content (string or list) to Converse content blocks.

    Handles:
      - Plain text strings → [{"text": "..."}]
      - Content arrays with text/image_url parts → mixed text/image blocks

    Filters out empty text blocks — Bedrock's Converse API rejects messages
    where a text content block has an empty ``text`` field (ValidationException:
    "text content blocks must be non-empty"). Ref: issue #9486.
    """
    if content is None:
        return [{"text": " "}]
    if isinstance(content, str):
        return [{"text": content}] if content.strip() else [{"text": " "}]
    if isinstance(content, list):
        blocks = []
        for part in content:
            if isinstance(part, str):
                blocks.append({"text": part})
                continue
            if not isinstance(part, dict):
                continue
            part_type = part.get("type", "")
            if part_type == "text":
                text = part.get("text", "")
                blocks.append({"text": text if text else " "})
            elif part_type == "image_url":
                image_url = part.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else ""
                if url.startswith("data:"):
                    # data:image/jpeg;base64,/9j/4AAQ...
                    header, _, data = url.partition(",")
                    media_type = "image/jpeg"
                    if header.startswith("data:"):
                        mime_part = header[5:].split(";")[0]
                        if mime_part:
                            media_type = mime_part
                    image_format = (
                        media_type.split("/")[-1]
                        if "/" in media_type
                        else "jpeg"
                    ).lower()
                    if image_format == "jpg":
                        image_format = "jpeg"
                    if image_format not in {"jpeg", "png", "gif", "webp"}:
                        raise ValueError(
                            f"Unsupported Bedrock image format: {image_format!r}"
                        )
                    blocks.append({
                        "image": {
                            "format": image_format,
                            "source": {"bytes": _decode_image_data_url(url)},
                        }
                    })
                else:
                    # Remote URL — Converse doesn't support URLs directly,
                    # include as text reference for the model.
                    blocks.append({"text": f"[Image: {url}]"})
        return blocks if blocks else [{"text": " "}]
    return [{"text": str(content)}]


def convert_messages_to_converse(
    messages: List[Dict],
) -> Tuple[Optional[List[Dict]], List[Dict]]:
    """Convert OpenAI-format messages to Bedrock Converse format.

    Returns ``(system_prompt, converse_messages)`` where:
      - ``system_prompt`` is a list of system content blocks (or None)
      - ``converse_messages`` is the conversation in Converse format

    Handles:
      - System messages → extracted as system prompt
      - User messages → ``{"role": "user", "content": [...]}``
      - Assistant messages → ``{"role": "assistant", "content": [...]}``
      - Tool calls → ``{"toolUse": {"toolUseId": ..., "name": ..., "input": ...}}``
      - Tool results → ``{"toolResult": {"toolUseId": ..., "content": [...]}}``

    Converse requires strict user/assistant alternation. Consecutive messages
    with the same role are merged into a single message.
    """
    system_blocks: List[Dict] = []
    converse_msgs: List[Dict] = []

    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content")

        if role == "system":
            # System messages become the system prompt
            if isinstance(content, str) and content.strip():
                system_blocks.append({"text": content})
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        system_blocks.append({"text": part.get("text", "")})
                    elif isinstance(part, str):
                        system_blocks.append({"text": part})
            continue

        if role == "tool":
            # Tool result messages → merge into the preceding user turn
            tool_call_id = msg.get("tool_call_id", "")
            result_content = content if isinstance(content, str) else json.dumps(content)
            tool_result_block = {
                "toolResult": {
                    "toolUseId": tool_call_id,
                    "content": [{"text": result_content}],
                }
            }
            # In Converse, tool results go in a "user" role message
            if converse_msgs and converse_msgs[-1]["role"] == "user":
                converse_msgs[-1]["content"].append(tool_result_block)
            else:
                converse_msgs.append({
                    "role": "user",
                    "content": [tool_result_block],
                })
            continue

        if role == "assistant":
            content_blocks = []
            # Convert text content
            if isinstance(content, str) and content.strip():
                content_blocks.append({"text": content})
            elif isinstance(content, list):
                content_blocks.extend(_convert_content_to_converse(content))

            # Convert tool calls
            tool_calls = msg.get("tool_calls", [])
            for tc in (tool_calls or []):
                fn = tc.get("function", {})
                args_str = fn.get("arguments", "{}")
                try:
                    args_dict = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args_dict = {}
                content_blocks.append({
                    "toolUse": {
                        "toolUseId": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": args_dict,
                    }
                })

            if not content_blocks:
                content_blocks = [{"text": " "}]

            # Merge with previous assistant message if needed (strict alternation)
            if converse_msgs and converse_msgs[-1]["role"] == "assistant":
                converse_msgs[-1]["content"].extend(content_blocks)
            else:
                converse_msgs.append({
                    "role": "assistant",
                    "content": content_blocks,
                })
            continue

        if role == "user":
            content_blocks = _convert_content_to_converse(content)
            # Merge with previous user message if needed (strict alternation)
            if converse_msgs and converse_msgs[-1]["role"] == "user":
                converse_msgs[-1]["content"].extend(content_blocks)
            else:
                converse_msgs.append({
                    "role": "user",
                    "content": content_blocks,
                })
            continue

    # Converse requires the first message to be from the user
    if converse_msgs and converse_msgs[0]["role"] != "user":
        converse_msgs.insert(0, {"role": "user", "content": [{"text": " "}]})

    # Converse requires the last message to be from the user
    if converse_msgs and converse_msgs[-1]["role"] != "user":
        converse_msgs.append({"role": "user", "content": [{"text": " "}]})

    return (system_blocks if system_blocks else None, converse_msgs)


# ---------------------------------------------------------------------------
# Response format conversion: Bedrock Converse → OpenAI
# ---------------------------------------------------------------------------

def _converse_stop_reason_to_openai(stop_reason: str) -> str:
    """Map Bedrock Converse stop reasons to OpenAI finish_reason values."""
    mapping = {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "content_filtered": "content_filter",
        "guardrail_intervened": "content_filter",
    }
    return mapping.get(stop_reason, "error")


def normalize_converse_response(response: Dict) -> SimpleNamespace:
    """Convert a Bedrock Converse API response to an OpenAI-compatible object.

    The agent loop in ``run_agent.py`` expects responses shaped like
    ``openai.ChatCompletion`` — this function bridges the gap.

    Returns a SimpleNamespace with:
      - ``.choices[0].message.content`` — text response
      - ``.choices[0].message.tool_calls`` — tool call list (if any)
      - ``.choices[0].finish_reason`` — stop/tool_calls/length
      - ``.usage`` — token usage stats
    """
    output = response.get("output", {})
    message = output.get("message", {})
    content_blocks = message.get("content", [])
    # Absence is not equivalent to a provider-confirmed end_turn.  Preserve it
    # as an error so tool-shaped output cannot be executed from a truncated or
    # malformed envelope.  Explicit end_turn/stop_sequence remain accepted
    # terminal states for Bedrock implementations that pair them with toolUse.
    stop_reason = response.get("stopReason")

    text_parts = []
    reasoning_parts = []
    tool_calls = []
    invalid_tool_batch = False
    had_tool_intent = False

    for block in content_blocks:
        if "text" in block:
            text_parts.append(block["text"])
        elif "reasoningContent" in block:
            reasoning = block["reasoningContent"]
            if isinstance(reasoning, dict):
                thinking_text = reasoning.get("text", "")
                if thinking_text:
                    reasoning_parts.append(str(thinking_text))
        elif "toolUse" in block:
            had_tool_intent = True
            tu = block["toolUse"]
            tool_input = tu.get("input", {}) if isinstance(tu, dict) else None
            if not isinstance(tu, dict) or not isinstance(tool_input, dict):
                invalid_tool_batch = True
                continue
            tool_calls.append(SimpleNamespace(
                id=tu.get("toolUseId", ""),
                type="function",
                function=SimpleNamespace(
                    name=tu.get("name", ""),
                    arguments=json.dumps(tool_input),
                ),
            ))

    if invalid_tool_batch:
        # Parallel tool batches are atomic: never execute a valid sibling when
        # another tool block is malformed.
        tool_calls = []

    # Build the message object
    msg = SimpleNamespace(
        role="assistant",
        content="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls if tool_calls else None,
        reasoning_content="\n\n".join(reasoning_parts) if reasoning_parts else None,
    )

    # Build usage stats
    usage_data = response.get("usage", {})
    usage = SimpleNamespace(
        prompt_tokens=usage_data.get("inputTokens", 0),
        completion_tokens=usage_data.get("outputTokens", 0),
        total_tokens=(
            usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0)
        ),
    )

    finish_reason = _converse_stop_reason_to_openai(stop_reason)
    if invalid_tool_batch:
        finish_reason = "error"
    elif tool_calls and finish_reason == "stop":
        finish_reason = "tool_calls"
    elif finish_reason == "tool_calls" and not tool_calls:
        finish_reason = "error"
    if tool_calls and finish_reason != "tool_calls":
        tool_calls = []
        msg.tool_calls = None

    choice = SimpleNamespace(
        index=0,
        message=msg,
        finish_reason=finish_reason,
    )

    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model=response.get("modelId", ""),
        _elevate_had_tool_intent=had_tool_intent,
    )


# ---------------------------------------------------------------------------
# Streaming response conversion
# ---------------------------------------------------------------------------

def normalize_converse_stream_events(event_stream) -> SimpleNamespace:
    """Consume a Bedrock ConverseStream event stream and build an OpenAI-compatible response.

    Processes the stream events in order:
      - ``messageStart`` — role info
      - ``contentBlockStart`` — new text or toolUse block
      - ``contentBlockDelta`` — incremental text or toolUse input
      - ``contentBlockStop`` — block complete
      - ``messageStop`` — stop reason
      - ``metadata`` — usage stats

    Returns the same shape as ``normalize_converse_response()``.
    """
    return stream_converse_with_callbacks(event_stream)


def stream_converse_with_callbacks(
    event_stream,
    on_text_delta=None,
    on_tool_start=None,
    on_reasoning_delta=None,
    on_event=None,
    on_interrupt_check=None,
) -> SimpleNamespace:
    """Process a Bedrock ConverseStream event stream with real-time callbacks.

    This is the core streaming function that powers both the CLI's live token
    display and the gateway's progressive message updates.

    Args:
        event_stream: The boto3 ``converse_stream()`` response containing a
            ``stream`` key with an iterable of events.
        on_text_delta: Called with each text chunk as it arrives. Only fires
            when no tool_use blocks have been seen (same semantics as the
            Anthropic and chat_completions streaming paths).
        on_tool_start: Called with the tool name when a toolUse block begins.
            Lets the TUI show a spinner while tool arguments are generated.
        on_reasoning_delta: Called with reasoning/thinking text chunks.
            Bedrock surfaces thinking via ``reasoning`` content block deltas
            on supported models (Claude 4.6+).
        on_event: Called for every provider event, including messageStart,
            metadata, and non-content keep-alive/progress events.  This is the
            authoritative activity signal for stale-stream detection.
        on_interrupt_check: Called on each event. Should return True if the
            agent has been interrupted and streaming should stop.

    Returns:
        An OpenAI-compatible SimpleNamespace response, identical in shape to
        ``normalize_converse_response()``.
    """
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[SimpleNamespace] = []
    current_tool: Optional[Dict] = None
    current_text_buffer: List[str] = []
    has_tool_use = False
    # A stream is not terminal until messageStop is observed.
    stop_reason = None
    usage_data: Dict[str, int] = {}
    invalid_tool_batch = False
    saw_message_stop = False
    invalid_event_order = False

    for event in event_stream.get("stream", []):
        if on_event:
            on_event(event)
        # Check for interrupt
        if on_interrupt_check and on_interrupt_check():
            break

        if saw_message_stop:
            if "metadata" in event:
                meta_usage = event["metadata"].get("usage", {})
                usage_data = {
                    "inputTokens": meta_usage.get("inputTokens", 0),
                    "outputTokens": meta_usage.get("outputTokens", 0),
                }
                continue
            invalid_event_order = True
            continue

        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get("start", {})
            if "toolUse" in start:
                has_tool_use = True
                # Flush any accumulated text
                if current_text_buffer:
                    text_parts.append("".join(current_text_buffer))
                    current_text_buffer = []
                current_tool = {
                    "toolUseId": start["toolUse"].get("toolUseId", ""),
                    "name": start["toolUse"].get("name", ""),
                    "input_json": "",
                }
                if on_tool_start:
                    on_tool_start(current_tool["name"])

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            if "text" in delta:
                text = delta["text"]
                current_text_buffer.append(text)
                # Fire text delta callback only when no tool calls are present
                # (same semantics as Anthropic/chat_completions streaming)
                if on_text_delta and not has_tool_use:
                    on_text_delta(text)
            elif "toolUse" in delta:
                if current_tool is not None:
                    current_tool["input_json"] += delta["toolUse"].get("input", "")
            elif "reasoningContent" in delta:
                # Claude 4.6+ on Bedrock surfaces thinking via reasoningContent
                reasoning = delta["reasoningContent"]
                if isinstance(reasoning, dict):
                    thinking_text = reasoning.get("text", "")
                    if thinking_text:
                        reasoning_parts.append(str(thinking_text))
                        if on_reasoning_delta:
                            on_reasoning_delta(thinking_text)

        elif "contentBlockStop" in event:
            if current_tool is not None:
                try:
                    input_dict = json.loads(current_tool["input_json"]) if current_tool["input_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    input_dict = None
                if not isinstance(input_dict, dict):
                    invalid_tool_batch = True
                else:
                    tool_calls.append(SimpleNamespace(
                        id=current_tool["toolUseId"],
                        type="function",
                        function=SimpleNamespace(
                            name=current_tool["name"],
                            arguments=json.dumps(input_dict),
                        ),
                    ))
                current_tool = None
            elif current_text_buffer:
                text_parts.append("".join(current_text_buffer))
                current_text_buffer = []

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get("stopReason")
            saw_message_stop = True

        elif "metadata" in event:
            meta_usage = event["metadata"].get("usage", {})
            usage_data = {
                "inputTokens": meta_usage.get("inputTokens", 0),
                "outputTokens": meta_usage.get("outputTokens", 0),
            }

    # Flush remaining text
    if current_text_buffer:
        text_parts.append("".join(current_text_buffer))
    if current_tool is not None:
        invalid_tool_batch = True
    if invalid_tool_batch or invalid_event_order:
        tool_calls = []

    msg = SimpleNamespace(
        role="assistant",
        content="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls if tool_calls else None,
        reasoning_content="\n\n".join(reasoning_parts) if reasoning_parts else None,
    )

    usage = SimpleNamespace(
        prompt_tokens=usage_data.get("inputTokens", 0),
        completion_tokens=usage_data.get("outputTokens", 0),
        total_tokens=(
            usage_data.get("inputTokens", 0) + usage_data.get("outputTokens", 0)
        ),
    )

    finish_reason = _converse_stop_reason_to_openai(stop_reason)
    if invalid_tool_batch or invalid_event_order:
        finish_reason = "error"
    elif tool_calls and finish_reason == "stop":
        finish_reason = "tool_calls"
    elif finish_reason == "tool_calls" and not tool_calls:
        finish_reason = "error"
    if tool_calls and finish_reason != "tool_calls":
        tool_calls = []
        msg.tool_calls = None

    choice = SimpleNamespace(
        index=0,
        message=msg,
        finish_reason=finish_reason,
    )

    return SimpleNamespace(
        choices=[choice],
        usage=usage,
        model="",
        _elevate_had_tool_intent=has_tool_use,
    )


# ---------------------------------------------------------------------------
# High-level API: call Bedrock Converse
# ---------------------------------------------------------------------------

def build_converse_kwargs(
    model: str,
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    max_tokens: int = 4096,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    stop_sequences: Optional[List[str]] = None,
    guardrail_config: Optional[Dict] = None,
    tool_choice: Any = None,
    parallel_tool_calls: Optional[bool] = None,
) -> Dict[str, Any]:
    """Build kwargs for ``bedrock-runtime.converse()`` or ``converse_stream()``.

    Converts OpenAI-format inputs to Converse API parameters.
    """
    system_prompt, converse_messages = convert_messages_to_converse(messages)

    kwargs: Dict[str, Any] = {
        "modelId": model,
        "messages": converse_messages,
        "inferenceConfig": {
            "maxTokens": max_tokens,
        },
    }

    if system_prompt:
        kwargs["system"] = system_prompt

    if temperature is not None:
        kwargs["inferenceConfig"]["temperature"] = temperature

    if top_p is not None:
        kwargs["inferenceConfig"]["topP"] = top_p

    if stop_sequences:
        kwargs["inferenceConfig"]["stopSequences"] = stop_sequences

    if parallel_tool_calls is not None and not isinstance(parallel_tool_calls, bool):
        raise ValueError("Bedrock parallel_tool_calls must be a boolean")

    normalized_tool_choice: Optional[str] = None
    selected_tool_name: Optional[str] = None
    if tool_choice is None:
        normalized_tool_choice = None
    elif isinstance(tool_choice, str):
        choice_text = tool_choice.strip()
        if choice_text in {"auto", "required", "none"}:
            normalized_tool_choice = choice_text
        elif choice_text:
            normalized_tool_choice = "function"
            selected_tool_name = choice_text
        else:
            raise ValueError("Bedrock tool_choice cannot be empty")
    elif isinstance(tool_choice, dict):
        choice_type = str(tool_choice.get("type") or "").strip().lower()
        if choice_type in {"auto", "required", "none"}:
            normalized_tool_choice = choice_type
        elif choice_type in {"function", "tool"}:
            fn = tool_choice.get("function")
            if isinstance(fn, dict):
                selected_tool_name = str(fn.get("name") or "").strip()
            if not selected_tool_name:
                selected_tool_name = str(tool_choice.get("name") or "").strip()
            if not selected_tool_name:
                raise ValueError("Bedrock function tool_choice is missing a tool name")
            normalized_tool_choice = "function"
        else:
            raise ValueError(f"Unsupported Bedrock tool_choice: {tool_choice!r}")
    else:
        raise ValueError(f"Unsupported Bedrock tool_choice: {tool_choice!r}")

    if tools and normalized_tool_choice != "none":
        converse_tools = convert_tools_to_converse(tools)
        if converse_tools:
            # Some Bedrock models don't support tool/function calling (e.g.
            # DeepSeek R1, reasoning-only models).  Sending toolConfig to
            # these models causes a ValidationException → retry loop → failure.
            # Strip tools for known non-tool-calling models and warn the user.
            # Ref: PR #7920 feedback from @ptlally, pattern from PR #4346.
            if _model_supports_tool_use(model):
                kwargs["toolConfig"] = {"tools": converse_tools}
                available_names = {
                    item.get("toolSpec", {}).get("name")
                    for item in converse_tools
                    if isinstance(item, dict)
                }
                if normalized_tool_choice == "auto":
                    kwargs["toolConfig"]["toolChoice"] = {"auto": {}}
                elif normalized_tool_choice == "required":
                    kwargs["toolConfig"]["toolChoice"] = {"any": {}}
                elif normalized_tool_choice == "function":
                    if selected_tool_name not in available_names:
                        raise ValueError(
                            f"Bedrock tool_choice selected unknown tool {selected_tool_name!r}"
                        )
                    kwargs["toolConfig"]["toolChoice"] = {
                        "tool": {"name": selected_tool_name}
                    }
                if parallel_tool_calls is False:
                    raise ValueError(
                        "Bedrock Converse cannot guarantee parallel_tool_calls=False"
                    )
            else:
                if normalized_tool_choice in {"required", "function"}:
                    raise ValueError(
                        f"Bedrock model {model!r} cannot satisfy required tool_choice"
                    )
                logger.warning(
                    "Model %s does not support tool calling — tools stripped. "
                    "The agent will operate in text-only mode.", model
                )
    elif normalized_tool_choice in {"required", "function"}:
        raise ValueError("Bedrock tool_choice requires at least one valid tool")

    if guardrail_config:
        kwargs["guardrailConfig"] = guardrail_config

    return kwargs


def call_converse(
    region: str,
    model: str,
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    max_tokens: int = 4096,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    stop_sequences: Optional[List[str]] = None,
    guardrail_config: Optional[Dict] = None,
    timeout: Optional[float] = None,
    endpoint_url: Optional[str] = None,
) -> SimpleNamespace:
    """Call Bedrock Converse API (non-streaming) and return an OpenAI-compatible response.

    This is the primary entry point for the agent loop when using the Bedrock provider.
    """
    client = _get_bedrock_runtime_client(
        region,
        timeout=timeout,
        endpoint_url=endpoint_url,
    )
    non_stream_guardrail = prepare_converse_guardrail_config(
        guardrail_config,
        streaming=False,
    )
    kwargs = build_converse_kwargs(
        model=model,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop_sequences=stop_sequences,
        guardrail_config=non_stream_guardrail,
    )

    try:
        response = client.converse(**kwargs)
    except Exception as exc:
        if is_stale_connection_error(exc):
            logger.warning(
                "bedrock: stale-connection error on converse(region=%s, model=%s): "
                "%s — evicting cached client so the next call reconnects.",
                region, model, type(exc).__name__,
            )
            invalidate_runtime_client(
                region,
                timeout=timeout,
                endpoint_url=endpoint_url,
                expected_client=client,
            )
        raise
    return normalize_converse_response(response)


def call_converse_stream(
    region: str,
    model: str,
    messages: List[Dict],
    tools: Optional[List[Dict]] = None,
    max_tokens: int = 4096,
    temperature: Optional[float] = None,
    top_p: Optional[float] = None,
    stop_sequences: Optional[List[str]] = None,
    guardrail_config: Optional[Dict] = None,
    timeout: Optional[float] = None,
    endpoint_url: Optional[str] = None,
) -> SimpleNamespace:
    """Call Bedrock ConverseStream API and return an OpenAI-compatible response.

    Consumes the full stream and returns the assembled response. For true
    streaming with delta callbacks, use ``iter_converse_stream()`` instead.
    """
    client = _get_bedrock_runtime_client(
        region,
        timeout=timeout,
        endpoint_url=endpoint_url,
    )
    stream_guardrail = prepare_converse_guardrail_config(
        guardrail_config,
        streaming=True,
    )
    kwargs = build_converse_kwargs(
        model=model,
        messages=messages,
        tools=tools,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop_sequences=stop_sequences,
        guardrail_config=stream_guardrail,
    )

    try:
        response = client.converse_stream(**kwargs)
        # Event-stream failures surface while iterating, often well after the
        # HTTP request itself succeeded.  Keep normalization inside the same
        # stale-client boundary so a mid-stream reset evicts the exact client
        # that produced it and never becomes a partial successful response.
        return normalize_converse_stream_events(response)
    except Exception as exc:
        if is_stale_connection_error(exc):
            logger.warning(
                "bedrock: stale-connection error on converse_stream(region=%s, "
                "model=%s): %s — evicting cached client so the next call reconnects.",
                region, model, type(exc).__name__,
            )
            invalidate_runtime_client(
                region,
                timeout=timeout,
                endpoint_url=endpoint_url,
                expected_client=client,
            )
        raise


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------

_discovery_cache: Dict[str, Any] = {}
_DISCOVERY_CACHE_TTL_SECONDS = 3600


def reset_discovery_cache():
    """Clear the model discovery cache. Used in tests."""
    _discovery_cache.clear()


def discover_bedrock_models(
    region: str,
    provider_filter: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Discover available Bedrock foundation models and inference profiles.

    Returns a list of model info dicts with keys:
      - ``id``: Model ID (e.g. "anthropic.claude-sonnet-4-6-20250514-v1:0")
      - ``name``: Human-readable name
      - ``provider``: Model provider (e.g. "Anthropic", "Amazon", "Meta")
      - ``input_modalities``: List of input types (e.g. ["TEXT", "IMAGE"])
      - ``output_modalities``: List of output types
      - ``streaming``: Whether streaming is supported

    Caches results for 1 hour per region to avoid repeated API calls.

    Mirrors OpenClaw's ``discoverBedrockModels()`` in
    ``extensions/amazon-bedrock/discovery.ts``.
    """
    import time

    cache_key = f"{region}:{','.join(sorted(provider_filter or []))}"
    cached = _discovery_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"]) < _DISCOVERY_CACHE_TTL_SECONDS:
        return cached["models"]

    try:
        client = _get_bedrock_control_client(region)
    except Exception as e:
        logger.warning("Failed to create Bedrock client for model discovery: %s", e)
        return []

    models = []
    seen_ids = set()
    filter_set = {f.lower() for f in (provider_filter or [])}

    # 1. Discover foundation models
    try:
        response = client.list_foundation_models()
        for summary in response.get("modelSummaries", []):
            model_id = (summary.get("modelId") or "").strip()
            if not model_id:
                continue

            # Apply provider filter
            if filter_set:
                provider_name = (summary.get("providerName") or "").lower()
                model_prefix = model_id.split(".")[0].lower() if "." in model_id else ""
                if provider_name not in filter_set and model_prefix not in filter_set:
                    continue

            # Only include active, streaming-capable, text-output models
            lifecycle = summary.get("modelLifecycle", {})
            if lifecycle.get("status", "").upper() != "ACTIVE":
                continue
            if not summary.get("responseStreamingSupported", False):
                continue
            output_mods = summary.get("outputModalities", [])
            if "TEXT" not in output_mods:
                continue

            models.append({
                "id": model_id,
                "name": (summary.get("modelName") or model_id).strip(),
                "provider": (summary.get("providerName") or "").strip(),
                "input_modalities": summary.get("inputModalities", []),
                "output_modalities": output_mods,
                "streaming": True,
            })
            seen_ids.add(model_id.lower())
    except Exception as e:
        logger.warning("Failed to list Bedrock foundation models: %s", e)

    # 2. Discover inference profiles (cross-region, better capacity)
    try:
        profiles = []
        next_token = None
        while True:
            kwargs = {}
            if next_token:
                kwargs["nextToken"] = next_token
            response = client.list_inference_profiles(**kwargs)
            for profile in response.get("inferenceProfileSummaries", []):
                profiles.append(profile)
            next_token = response.get("nextToken")
            if not next_token:
                break

        for profile in profiles:
            profile_id = (profile.get("inferenceProfileId") or "").strip()
            if not profile_id:
                continue
            if profile.get("status") != "ACTIVE":
                continue
            if profile_id.lower() in seen_ids:
                continue

            # Apply provider filter to underlying models
            if filter_set:
                profile_models = profile.get("models", [])
                matches = any(
                    _extract_provider_from_arn(m.get("modelArn", "")).lower() in filter_set
                    for m in profile_models
                )
                if not matches:
                    continue

            models.append({
                "id": profile_id,
                "name": (profile.get("inferenceProfileName") or profile_id).strip(),
                "provider": "inference-profile",
                "input_modalities": ["TEXT"],
                "output_modalities": ["TEXT"],
                "streaming": True,
            })
            seen_ids.add(profile_id.lower())
    except Exception as e:
        logger.debug("Skipping inference profile discovery: %s", e)

    # Sort: global cross-region profiles first (recommended), then alphabetical
    models.sort(key=lambda m: (
        0 if m["id"].startswith("global.") else 1,
        m["name"].lower(),
    ))

    _discovery_cache[cache_key] = {
        "timestamp": time.time(),
        "models": models,
    }
    return models


def _extract_provider_from_arn(arn: str) -> str:
    """Extract the model provider from a Bedrock model ARN.

    Example: "arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-v2"
    → "anthropic"
    """
    match = re.search(r"foundation-model/([^.]+)", arn)
    return match.group(1) if match else ""


def get_bedrock_model_ids(region: str) -> List[str]:
    """Return a flat list of available Bedrock model IDs for the given region.

    Convenience wrapper around ``discover_bedrock_models()`` for use in
    the model selection UI.
    """
    models = discover_bedrock_models(region)
    return [m["id"] for m in models]


# ---------------------------------------------------------------------------
# Error classification — Bedrock-specific exceptions
# ---------------------------------------------------------------------------
# Mirrors OpenClaw's classifyFailoverReason() and matchesContextOverflowError()
# in extensions/amazon-bedrock/register.sync.runtime.ts.

# Patterns that indicate the input context exceeded the model's token limit.
# Used by run_agent.py to trigger context compression instead of retrying.
CONTEXT_OVERFLOW_PATTERNS = [
    re.compile(r"ValidationException.*(?:input is too long|max input token|input token.*exceed)", re.IGNORECASE),
    re.compile(r"ValidationException.*(?:exceeds? the (?:maximum|max) (?:number of )?(?:input )?tokens)", re.IGNORECASE),
    re.compile(r"ModelStreamErrorException.*(?:Input is too long|too many input tokens)", re.IGNORECASE),
]

# Patterns for throttling / rate limit errors — should trigger backoff + retry.
THROTTLE_PATTERNS = [
    re.compile(r"ThrottlingException", re.IGNORECASE),
    re.compile(r"Too many concurrent requests", re.IGNORECASE),
    re.compile(r"ServiceQuotaExceededException", re.IGNORECASE),
]

# Patterns for transient overload — model is temporarily unavailable.
OVERLOAD_PATTERNS = [
    re.compile(r"ModelNotReadyException", re.IGNORECASE),
    re.compile(r"ModelTimeoutException", re.IGNORECASE),
    re.compile(r"InternalServerException", re.IGNORECASE),
]


def is_context_overflow_error(error_message: str) -> bool:
    """Return True if the error indicates the input context was too large.

    When this returns True, the agent should compress context and retry
    rather than treating it as a fatal error.
    """
    return any(p.search(error_message) for p in CONTEXT_OVERFLOW_PATTERNS)


def classify_bedrock_error(error_message: str) -> str:
    """Classify a Bedrock error for retry/failover decisions.

    Returns:
      - ``"context_overflow"`` — input too long, compress and retry
      - ``"rate_limit"`` — throttled, backoff and retry
      - ``"overloaded"`` — model temporarily unavailable, retry with delay
      - ``"unknown"`` — unclassified error
    """
    if is_context_overflow_error(error_message):
        return "context_overflow"
    if any(p.search(error_message) for p in THROTTLE_PATTERNS):
        return "rate_limit"
    if any(p.search(error_message) for p in OVERLOAD_PATTERNS):
        return "overloaded"
    return "unknown"


# ---------------------------------------------------------------------------
# Bedrock model context lengths
# ---------------------------------------------------------------------------
# Static fallback table for models where the Bedrock API doesn't expose
# context window sizes.  Used by agent/model_metadata.py when dynamic
# detection is unavailable.

BEDROCK_CONTEXT_LENGTHS: Dict[str, int] = {
    # Anthropic Claude models on Bedrock
    "anthropic.claude-opus-4-6":     200_000,
    "anthropic.claude-sonnet-4-6":   200_000,
    "anthropic.claude-sonnet-4-5":   200_000,
    "anthropic.claude-haiku-4-5":    200_000,
    "anthropic.claude-opus-4":       200_000,
    "anthropic.claude-sonnet-4":     200_000,
    "anthropic.claude-3-5-sonnet":   200_000,
    "anthropic.claude-3-5-haiku":    200_000,
    "anthropic.claude-3-opus":       200_000,
    "anthropic.claude-3-sonnet":     200_000,
    "anthropic.claude-3-haiku":      200_000,
    # Amazon Nova
    "amazon.nova-pro":               300_000,
    "amazon.nova-lite":              300_000,
    "amazon.nova-micro":             128_000,
    # Meta Llama
    "meta.llama4-maverick":          128_000,
    "meta.llama4-scout":             128_000,
    "meta.llama3-3-70b-instruct":    128_000,
    # Mistral
    "mistral.mistral-large":         128_000,
    # DeepSeek
    "deepseek.v3":                   128_000,
}

# Default for unknown Bedrock models
BEDROCK_DEFAULT_CONTEXT_LENGTH = 128_000


def get_bedrock_context_length(model_id: str) -> int:
    """Look up the context window size for a Bedrock model.

    Uses substring matching so versioned IDs like
    ``anthropic.claude-sonnet-4-6-20250514-v1:0`` resolve correctly.
    """
    model_lower = model_id.lower()
    best_key = ""
    best_val = BEDROCK_DEFAULT_CONTEXT_LENGTH
    for key, val in BEDROCK_CONTEXT_LENGTHS.items():
        if key in model_lower and len(key) > len(best_key):
            best_key = key
            best_val = val
    return best_val
