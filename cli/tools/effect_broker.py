"""Durable effect claim/receipt broker for the general registry shadow path.

``0bbb80997`` bound the exact-Beta *terminal* tool to durable one-winner
claims and terminal receipts.  This module generalizes that machinery to
every accepted-turn registry tool whose resolved effects go beyond pure
read, at the atomic shadow boundary (``registry._start_prepared_shadow``).

Scope and posture (deliberately identical to the terminal machinery):

* **Exact Realtor Beta only.**  The broker never engages outside
  ``beta_provider_policy_active()`` — Stable dispatch stays byte-identical.
  Enforcement *flip* semantics beyond exact Beta belong to package A5.
* **One winner per durable invocation identity.**  A claim is an atomic
  INSERT keyed ``UNIQUE(session_id, invocation_id)``; duplicate or
  restart claims can never re-invoke the handler.
* **Pre-claim revalidation.**  Before claiming, the frozen
  ``PreparedToolCall`` is revalidated from first principles: canonical
  args/handler-kwargs digests are recomputed, the effect set is re-checked
  for UNKNOWN, and the policy authorization is re-evaluated — the frozen
  ``authorization`` field is never trusted on its own.
* **Terminal receipts.**  Every claim ends ``succeeded`` / ``failed`` /
  ``unknown``.  Receipt-persistence failure after a successful handler run
  suppresses success: the model sees a typed unknown-outcome payload, never
  an unproven success.
* **Crash windows terminalize.**  ``claimed`` rows from a different logical
  boot become ``unknown`` at first broker use of a store (same
  ``_APPROVAL_BOOT_ID`` lease authority as Approval Grants).
* **Result-transform evidence.**  Receipts record the pre-transform result
  digest; :func:`bind_transformed_result` is the only way a downstream
  rewrite becomes legitimate model-visible output, and its store CAS
  structurally cannot modify the recorded outcome.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Typed shadow_status codes surfaced by the registry when the broker refuses.
CLAIM_STATUS_CONFLICT = "effect_claim_conflict"
CLAIM_STATUS_UNAVAILABLE = "effect_claim_unavailable"
CLAIM_STATUS_REVALIDATION = "effect_claim_block"
RECEIPT_STATUS_UNAVAILABLE = "effect_receipt_unavailable"


def _beta_effect_broker_active() -> bool:
    """Exact-Beta gate; environment fallback keeps a broken bundle closed."""
    import os

    try:
        from elevate_cli.beta_provider_policy import beta_provider_policy_active

        return beta_provider_policy_active()
    except Exception:
        return os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"


@dataclass(frozen=True, slots=True)
class ToolEffectClaim:
    """One durable registry-effect claim; possession never implies success."""

    claim_id: str
    boot_id: str
    session_id: str
    invocation_id: str
    tool_name: str
    args_digest: str
    store: Any


@dataclass(frozen=True, slots=True)
class EffectClaimDecision:
    """Outcome of one claim attempt.  ``claim`` is None on every refusal."""

    claim: Optional[ToolEffectClaim]
    status_code: str = ""
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ToolEffectReceiptRef:
    """In-process anchor from one completed claim to its durable receipt.

    ``expected_result_digests`` are the only digests the model-visible
    result may carry when it leaves the governed boundary; anything else is
    an unevidenced rewrite and fails closed under exact Beta.
    """

    claim_id: str
    session_id: str
    invocation_id: str
    tool_name: str
    final_status: str
    expected_result_digests: frozenset


def model_result_digest(result: Any) -> str:
    """Canonical SHA-256 digest of one model-visible tool result."""
    if isinstance(result, str):
        return hashlib.sha256(result.encode("utf-8")).hexdigest()
    try:
        canonical = json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=repr,
        )
    except Exception:
        canonical = repr(result)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def claim_required_for_effects(effects: Any) -> bool:
    """Whether a resolved effect set needs a durable claim (beyond pure read).

    UNKNOWN counts as beyond-read: it should never reach the claim seam
    (exact-Beta authorization denies it first), but if it ever did, the
    fail-safe posture is to demand a claim rather than exempt it.
    """
    from tools.approval import EffectKind

    try:
        effect_list = list(effects or ())
    except TypeError:
        return True
    if not effect_list:
        return True
    for effect in effect_list:
        kind = getattr(effect, "kind", None)
        if kind is not EffectKind.READ:
            return True
    return False


# ---------------------------------------------------------------------------
# Store resolution + once-per-path prior-boot cleanup
# ---------------------------------------------------------------------------

_STORE_UNSET = object()
# Tests may point the broker at an isolated SessionDB (or None to simulate an
# unavailable store).  Production always resolves the default state.db
# authority shared with Approval Grants.
_store_override: Any = _STORE_UNSET
_init_lock = threading.Lock()
_initialized_store_keys: set[str] = set()


def _store_key(store: Any) -> str:
    path = getattr(store, "db_path", None)
    if path is not None:
        try:
            return str(path.expanduser().resolve())
        except Exception:
            return str(path)
    return f"object:{id(store)}"


def _record_startup_tool_effect_cleanup(receipt: dict) -> None:
    """Project a prior-boot crash window without calling it failure/success."""
    try:
        from elevate_cli.diagnostics.session_recorder import record_session_event

        record_session_event(
            "tool.effect_receipt",
            session_id=receipt.get("session_id") or None,
            correlation_id=None,
            payload={
                "claim_id": receipt.get("claim_id"),
                "invocation_id": receipt.get("invocation_id"),
                "tool_name": receipt.get("tool_name"),
                "status": "unknown",
                "reason": receipt.get("failure_code") or "prior_boot_crash_window",
            },
            severity="warning",
            source="effect_broker",
            component="tools.effect_broker",
        )
    except Exception:
        logger.debug(
            "tool effect startup cleanup projection failed", exc_info=True
        )


def _initialize_store(store: Any) -> Optional[Any]:
    """Activate the boot lease and terminalize prior-boot claims once per DB."""
    from tools.approval import _APPROVAL_BOOT_ID, _initialize_approval_store

    cleanup = getattr(store, "mark_prior_boot_tool_effects_unknown", None)
    claim_fn = getattr(store, "claim_tool_effect", None)
    complete_fn = getattr(store, "complete_tool_effect", None)
    if not callable(cleanup) or not callable(claim_fn) or not callable(complete_fn):
        logger.error("tool effect persistence is unavailable on this store")
        return None
    key = _store_key(store)
    with _init_lock:
        already = key in _initialized_store_keys
    if already:
        return store
    try:
        # Shares the Approval Grant boot lease authority: one live logical
        # boot per state DB.  This also runs the grant-side startup cleanup
        # exactly once per path (idempotent when approval already ran it).
        _initialize_approval_store(store)
        unknown = cleanup(_APPROVAL_BOOT_ID)
    except Exception:
        logger.error(
            "tool effect broker startup cleanup failed closed", exc_info=True
        )
        return None
    with _init_lock:
        _initialized_store_keys.add(key)
    for receipt in unknown or []:
        if isinstance(receipt, dict):
            _record_startup_tool_effect_cleanup(receipt)
    return store


def _resolve_store() -> Optional[Any]:
    """Return an initialized durable store, or None (callers fail closed)."""
    if _store_override is not _STORE_UNSET:
        store = _store_override
    else:
        from tools.approval import _get_default_approval_store

        store = _get_default_approval_store()
    if store is None:
        return None
    return _initialize_store(store)


def _reset_for_tests() -> None:
    """Clear override + init memo.  Test-only seam."""
    global _store_override
    with _init_lock:
        _store_override = _STORE_UNSET
        _initialized_store_keys.clear()


# ---------------------------------------------------------------------------
# Claim / complete
# ---------------------------------------------------------------------------

def _sha256_utf8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _revalidate_prepared(prepared: Any) -> Optional[str]:
    """Re-derive every claim precondition from the frozen call.  None = OK."""
    from tools.approval import EffectKind, ExecutionPolicy, authorize_effects

    if getattr(prepared, "preparation_error", None) is not None:
        return "prepared call carries a preparation error"
    if getattr(prepared, "effect_resolution_error", None) is not None:
        return "prepared call carries an effect resolution error"
    if getattr(prepared, "entry_id", None) is None:
        return "prepared call has no registry entry identity"
    context = getattr(prepared, "context", None)
    policy = getattr(prepared, "execution_policy", None)
    if context is None:
        return "prepared call has no durable context"
    if not isinstance(policy, ExecutionPolicy):
        return "prepared call has no accepted-turn policy"
    if getattr(context, "accepted_turn_id", None) != policy.accepted_turn_id:
        return "prepared context turn does not match the accepted policy"
    revision = getattr(context, "policy_revision", None)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return "prepared policy revision is invalid"

    args_json = getattr(prepared, "canonical_args_json", None)
    args_digest = getattr(prepared, "args_digest", None)
    if not isinstance(args_json, str) or not isinstance(args_digest, str):
        return "prepared call has no canonical argument snapshot"
    if _sha256_utf8(args_json) != args_digest:
        return "prepared argument digest does not match its snapshot"
    kwargs_json = getattr(prepared, "canonical_handler_kwargs_json", None)
    kwargs_digest = getattr(prepared, "handler_kwargs_digest", None)
    if kwargs_json is not None or kwargs_digest is not None:
        if not isinstance(kwargs_json, str) or not isinstance(kwargs_digest, str):
            return "prepared call has an incomplete handler-kwargs snapshot"
        if _sha256_utf8(kwargs_json) != kwargs_digest:
            return "prepared handler-kwargs digest does not match its snapshot"

    effects = getattr(prepared, "resolved_effects", None) or frozenset()
    if not effects:
        return "prepared call resolved no effects"
    if any(getattr(effect, "kind", None) is EffectKind.UNKNOWN for effect in effects):
        return "prepared call resolved an unknown effect"
    authorization = authorize_effects(policy, effects)
    if not authorization.allowed:
        return "prepared effects exceed the accepted-turn policy"
    return None


def acquire_prepared_effect_claim(prepared: Any) -> EffectClaimDecision:
    """Revalidate and durably claim one beyond-read prepared invocation.

    Only meaningful under exact Beta (callers gate on it); outside Beta this
    refuses so a miswired caller cannot quietly build a fake trail.
    """
    if not _beta_effect_broker_active():
        return EffectClaimDecision(
            claim=None,
            status_code=CLAIM_STATUS_UNAVAILABLE,
            detail="the durable effect broker only operates under exact Beta",
        )
    reason = _revalidate_prepared(prepared)
    if reason is not None:
        return EffectClaimDecision(
            claim=None,
            status_code=CLAIM_STATUS_REVALIDATION,
            detail=f"effect claim revalidation failed: {reason}",
        )
    store = _resolve_store()
    if store is None:
        return EffectClaimDecision(
            claim=None,
            status_code=CLAIM_STATUS_UNAVAILABLE,
            detail=(
                "the durable effect store is unavailable; the tool effect "
                "cannot be claimed"
            ),
        )

    from tools.approval import _APPROVAL_BOOT_ID

    context = prepared.context
    policy = prepared.execution_policy
    claim_id = uuid.uuid4().hex
    try:
        receipt = store.claim_tool_effect(
            claim_id=claim_id,
            boot_id=_APPROVAL_BOOT_ID,
            session_id=context.session_id,
            invocation_id=context.invocation_id,
            turn_id=policy.accepted_turn_id,
            tool_name=prepared.tool_name,
            entry_id=prepared.entry_id,
            registry_generation=prepared.registry_generation,
            canonical_args_digest=prepared.args_digest,
            handler_kwargs_digest=prepared.handler_kwargs_digest,
            accepted_policy=policy.to_dict(),
            policy_revision=context.policy_revision,
            effect_set=sorted(str(effect) for effect in prepared.resolved_effects),
        )
    except Exception:
        logger.error("tool effect claim persistence failed", exc_info=True)
        return EffectClaimDecision(
            claim=None,
            status_code=CLAIM_STATUS_UNAVAILABLE,
            detail=(
                "the durable effect claim could not be persisted; the tool "
                "effect was not started"
            ),
        )
    if not isinstance(receipt, dict) or receipt.get("status") != "claimed":
        return EffectClaimDecision(
            claim=None,
            status_code=CLAIM_STATUS_CONFLICT,
            detail=(
                "this tool invocation identity was already claimed; a "
                "duplicate or restarted call can never re-invoke the effect"
            ),
        )
    return EffectClaimDecision(
        claim=ToolEffectClaim(
            claim_id=claim_id,
            boot_id=_APPROVAL_BOOT_ID,
            session_id=context.session_id,
            invocation_id=context.invocation_id,
            tool_name=prepared.tool_name,
            args_digest=prepared.args_digest,
            store=store,
        )
    )


def finish_effect_claim(
    claim: ToolEffectClaim,
    *,
    status: str,
    result_identity: Any = None,
    failure_code: Optional[str] = None,
) -> str:
    """Persist the terminal receipt; the return value is the durable truth.

    Mirrors the terminal tool's ``_finish_approval_effect_claim``: a failed
    write degrades to a durable ``unknown`` attempt; receipt loss is never
    converted into the requested status.
    """
    if not isinstance(claim, ToolEffectClaim):
        raise TypeError("claim must be a ToolEffectClaim")
    result_digest = (
        model_result_digest(result_identity)
        if result_identity is not None
        else None
    )
    try:
        if claim.store.complete_tool_effect(
            claim_id=claim.claim_id,
            boot_id=claim.boot_id,
            status=status,
            result_digest=result_digest,
            failure_code=failure_code,
        ) == 1:
            return status
    except Exception:
        logger.error("tool effect receipt persistence failed", exc_info=True)
    if status != "unknown":
        try:
            if claim.store.complete_tool_effect(
                claim_id=claim.claim_id,
                boot_id=claim.boot_id,
                status="unknown",
                result_digest=None,
                failure_code="final_receipt_unavailable",
            ) == 1:
                return "unknown"
        except Exception:
            logger.error(
                "tool effect unknown-state persistence failed", exc_info=True
            )
    return "unknown"


def effect_receipt_unavailable_payload(tool_name: str) -> str:
    """Typed model-visible payload replacing an unprovable success."""
    return json.dumps(
        {
            "error": (
                f"Tool '{tool_name}' ran, but Elevate could not durably "
                "record its outcome. Do not assume it succeeded and do not "
                "retry it automatically; inspect the target state first."
            ),
            "shadow_status": RECEIPT_STATUS_UNAVAILABLE,
        },
        ensure_ascii=False,
    )


def effect_outcome_unknown_payload(tool_name: str) -> str:
    """Typed model-visible payload when the invocation started but its
    outcome is unknowable (e.g. an abandoned async worker past its
    ``_run_async`` timeout — the effect may still be applying)."""
    return json.dumps(
        {
            "error": (
                f"Tool '{tool_name}' may have started, but Elevate could not "
                "prove its final outcome. Do not retry it automatically; "
                "inspect the target state first."
            ),
            "shadow_status": "effect_outcome_unknown",
        },
        ensure_ascii=False,
    )


def result_tamper_payload(tool_name: str) -> str:
    """Typed model-visible payload replacing an unevidenced result rewrite."""
    return json.dumps(
        {
            "error": (
                f"Tool '{tool_name}' produced a result, but it was rewritten "
                "after execution without receipt-bound evidence. The rewritten "
                "output was withheld."
            ),
            "shadow_status": "effect_result_tamper",
        },
        ensure_ascii=False,
    )


def durable_transformed_digest(claim_id: str) -> Optional[str]:
    """Return the receipt's bound post-transform digest, if any.

    The exact-Beta result-integrity guard consults this on a digest
    mismatch: a rewrite that was evidenced via
    :func:`bind_transformed_result` is legitimate model-visible output;
    anything else stays fail-closed.
    """
    if not isinstance(claim_id, str) or not claim_id:
        return None
    store = _resolve_store()
    if store is None:
        return None
    getter = getattr(store, "get_tool_effect_receipt", None)
    if not callable(getter):
        return None
    try:
        receipt = getter(claim_id)
    except Exception:
        logger.debug("tool effect receipt lookup failed", exc_info=True)
        return None
    if not isinstance(receipt, dict):
        return None
    digest = receipt.get("transformed_result_digest")
    return digest if isinstance(digest, str) and digest else None


def bind_transformed_result(
    claim_or_ref: Any,
    original_result: Any,
    transformed_result: Any,
) -> bool:
    """Evidence one post-execution rewrite against its terminal receipt.

    Returns True only when the store CAS bound the pre/post digest pair to
    the receipt.  The CAS is anchored to the recorded pre-transform digest
    and is single-set, so it can never alter the receipt's recorded outcome
    and a second, different rewrite is refused.
    """
    claim_id = getattr(claim_or_ref, "claim_id", None)
    boot_id = getattr(claim_or_ref, "boot_id", None)
    store = getattr(claim_or_ref, "store", None)
    if store is None or not claim_id:
        return False
    if boot_id is None:
        from tools.approval import _APPROVAL_BOOT_ID

        boot_id = _APPROVAL_BOOT_ID
    try:
        return (
            store.record_tool_effect_result_transform(
                claim_id=claim_id,
                boot_id=boot_id,
                original_result_digest=model_result_digest(original_result),
                transformed_result_digest=model_result_digest(
                    transformed_result
                ),
            )
            == 1
        )
    except Exception:
        logger.error(
            "tool effect transform evidence persistence failed", exc_info=True
        )
        return False
