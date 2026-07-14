"""OpenAI-compatible facade that talks to Google's Cloud Code Assist backend.

This adapter lets Elevate use the ``google-gemini-cli`` provider as if it were
a standard OpenAI-shaped chat completion endpoint, while the underlying HTTP
traffic goes to ``cloudcode-pa.googleapis.com/v1internal:{generateContent,
streamGenerateContent}`` with a Bearer access token obtained via OAuth PKCE.

Architecture
------------
- ``GeminiCloudCodeClient`` exposes ``.chat.completions.create(**kwargs)``
  mirroring the subset of the OpenAI SDK that ``run_agent.py`` uses.
- Incoming OpenAI ``messages[]`` / ``tools[]`` / ``tool_choice`` are translated
  to Gemini's native ``contents[]`` / ``tools[].functionDeclarations`` /
  ``toolConfig`` / ``systemInstruction`` shape.
- The request body is wrapped ``{project, model, user_prompt_id, request}``
  per Code Assist API expectations.
- Responses (``candidates[].content.parts[]``) are converted back to
  OpenAI ``choices[0].message`` shape with ``content`` + ``tool_calls``.
- Streaming uses SSE (``?alt=sse``) and yields OpenAI-shaped delta chunks.

Attribution
-----------
Translation semantics follow jenslys/opencode-gemini-auth (MIT) and the public
Gemini API docs. Request envelope shape
(``{project, model, user_prompt_id, request}``) is documented nowhere; it is
reverse-engineered from the opencode-gemini-auth and clawdbot implementations.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from types import SimpleNamespace
from typing import Any, Dict, Iterator, List, Optional

import httpx

from agent import google_oauth
from agent.gemini_native_adapter import (
    _build_gemini_diagnostic as _build_native_gemini_diagnostic,
    _gemini_diagnostic_count,
    _map_gemini_finish_reason,
    _parse_gemini_function_call,
)
from agent.gemini_schema import sanitize_gemini_tool_parameters
from agent.google_code_assist import (
    CODE_ASSIST_ENDPOINT,
    CodeAssistError,
    ProjectContext,
    resolve_project_context,
)

logger = logging.getLogger(__name__)


_GEMINI_DIAGNOSTIC_ENUM = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_GEMINI_UNSPECIFIED_ENUMS = {
    "UNSPECIFIED",
    "BLOCK_REASON_UNSPECIFIED",
    "FINISH_REASON_UNSPECIFIED",
}
_STREAM_TOOL_BATCH_VALID = 0
_STREAM_TOOL_BATCH_INVALID = 1
_STREAM_TOOL_BATCH_ERROR_EMITTED = 2


def _stream_tool_batch_state(tool_call_counter: List[int]) -> int:
    if len(tool_call_counter) < 2:
        return _STREAM_TOOL_BATCH_VALID
    return tool_call_counter[1]


def _poison_stream_tool_batch(tool_call_counter: List[int]) -> None:
    """Clear the call count and persist a poisoned parallel-batch marker."""
    tool_call_counter[0] = 0
    if len(tool_call_counter) < 2:
        tool_call_counter.append(_STREAM_TOOL_BATCH_INVALID)
    else:
        tool_call_counter[1] = _STREAM_TOOL_BATCH_INVALID


def _cloudcode_diagnostic_enum(value: Any, *, present: bool) -> str:
    """Normalize a provider enum without treating malformed values as absent."""
    if not present:
        return "UNSPECIFIED"
    if not isinstance(value, str):
        return "INVALID"
    normalized = value.strip().upper()
    if normalized in _GEMINI_UNSPECIFIED_ENUMS:
        return "UNSPECIFIED"
    if normalized.endswith("_UNSPECIFIED"):
        return "INVALID"
    if _GEMINI_DIAGNOSTIC_ENUM.fullmatch(normalized):
        return normalized
    return "INVALID"


def _build_gemini_diagnostic(
    payload: Dict[str, Any],
    candidate: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build native-parity diagnostics with fail-closed CloudCode enums."""
    diagnostic = _build_native_gemini_diagnostic(payload, candidate)
    candidate = candidate if isinstance(candidate, dict) else {}
    diagnostic["finish_reason"] = _cloudcode_diagnostic_enum(
        candidate.get("finishReason"),
        present="finishReason" in candidate,
    )

    prompt_feedback_present = "promptFeedback" in payload
    prompt_feedback = payload.get("promptFeedback")
    if not prompt_feedback_present:
        prompt_block_reason = "UNSPECIFIED"
    elif not isinstance(prompt_feedback, dict):
        prompt_block_reason = "INVALID"
    else:
        prompt_block_reason = _cloudcode_diagnostic_enum(
            prompt_feedback.get("blockReason"),
            present="blockReason" in prompt_feedback,
        )
    diagnostic["prompt_block_reason"] = prompt_block_reason
    return diagnostic


# =============================================================================
# Request translation: OpenAI → Gemini
# =============================================================================

_ROLE_MAP_OPENAI_TO_GEMINI = {
    "user": "user",
    "assistant": "model",
    "system": "user",  # handled separately via systemInstruction
    "tool": "user",  # functionResponse is wrapped in a user-role turn
    "function": "user",
}


def _coerce_content_to_text(content: Any) -> str:
    """OpenAI content may be str or a list of parts; reduce to plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: List[str] = []
        for p in content:
            if isinstance(p, str):
                pieces.append(p)
            elif isinstance(p, dict):
                if p.get("type") == "text" and isinstance(p.get("text"), str):
                    pieces.append(p["text"])
                # Multimodal (image_url, etc.) — stub for now; log and skip
                elif p.get("type") in {"image_url", "input_audio"}:
                    logger.debug(
                        "Dropping multimodal part (not yet supported): %s",
                        p.get("type"),
                    )
        return "\n".join(pieces)
    return str(content)


def _translate_tool_call_to_gemini(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI tool_call -> Gemini functionCall part."""
    fn = tool_call.get("function") or {}
    args_raw = fn.get("arguments", "")
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) and args_raw else {}
    except json.JSONDecodeError:
        args = {"_raw": args_raw}
    if not isinstance(args, dict):
        args = {"_value": args}
    return {
        "functionCall": {
            "name": fn.get("name") or "",
            "args": args,
        },
        # Sentinel signature — matches opencode-gemini-auth's approach.
        # Without this, Code Assist rejects function calls that originated
        # outside its own chain.
        "thoughtSignature": "skip_thought_signature_validator",
    }


def _translate_tool_result_to_gemini(message: Dict[str, Any]) -> Dict[str, Any]:
    """OpenAI tool-role message -> Gemini functionResponse part.

    The function name isn't in the OpenAI tool message directly; it must be
    passed via the assistant message that issued the call. For simplicity we
    look up ``name`` on the message (OpenAI SDK copies it there) or on the
    ``tool_call_id`` cross-reference.
    """
    name = str(message.get("name") or message.get("tool_call_id") or "tool")
    content = _coerce_content_to_text(message.get("content"))
    # Gemini expects the response as a dict under `response`. We wrap plain
    # text in {"output": "..."}.
    try:
        parsed = json.loads(content) if content.strip().startswith(("{", "[")) else None
    except json.JSONDecodeError:
        parsed = None
    response = parsed if isinstance(parsed, dict) else {"output": content}
    return {
        "functionResponse": {
            "name": name,
            "response": response,
        },
    }


def _build_gemini_contents(
    messages: List[Dict[str, Any]],
) -> tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Convert OpenAI messages[] to Gemini contents[] + systemInstruction."""
    system_text_parts: List[str] = []
    contents: List[Dict[str, Any]] = []

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")

        if role == "system":
            system_text_parts.append(_coerce_content_to_text(msg.get("content")))
            continue

        # Tool result message — emit a user-role turn with functionResponse
        if role == "tool" or role == "function":
            contents.append(
                {
                    "role": "user",
                    "parts": [_translate_tool_result_to_gemini(msg)],
                }
            )
            continue

        gemini_role = _ROLE_MAP_OPENAI_TO_GEMINI.get(role, "user")
        parts: List[Dict[str, Any]] = []

        text = _coerce_content_to_text(msg.get("content"))
        if text:
            parts.append({"text": text})

        # Assistant messages can carry tool_calls
        tool_calls = msg.get("tool_calls") or []
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                if isinstance(tc, dict):
                    parts.append(_translate_tool_call_to_gemini(tc))

        if not parts:
            # Gemini rejects empty parts; skip the turn entirely
            continue

        contents.append({"role": gemini_role, "parts": parts})

    system_instruction: Optional[Dict[str, Any]] = None
    joined_system = "\n".join(p for p in system_text_parts if p).strip()
    if joined_system:
        system_instruction = {
            "role": "system",
            "parts": [{"text": joined_system}],
        }

    return contents, system_instruction


def _translate_tools_to_gemini(tools: Any) -> List[Dict[str, Any]]:
    """OpenAI tools[] -> Gemini tools[].functionDeclarations[]."""
    if not isinstance(tools, list) or not tools:
        return []
    declarations: List[Dict[str, Any]] = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        fn = t.get("function") or {}
        if not isinstance(fn, dict):
            continue
        name = fn.get("name")
        if not name:
            continue
        decl = {"name": str(name)}
        if fn.get("description"):
            decl["description"] = str(fn["description"])
        params = fn.get("parameters")
        if isinstance(params, dict):
            decl["parameters"] = sanitize_gemini_tool_parameters(params)
        declarations.append(decl)
    if not declarations:
        return []
    return [{"functionDeclarations": declarations}]


def _translate_tool_choice_to_gemini(tool_choice: Any) -> Optional[Dict[str, Any]]:
    """OpenAI tool_choice -> Gemini toolConfig.functionCallingConfig."""
    if tool_choice is None:
        return None
    if isinstance(tool_choice, str):
        if tool_choice == "auto":
            return {"functionCallingConfig": {"mode": "AUTO"}}
        if tool_choice == "required":
            return {"functionCallingConfig": {"mode": "ANY"}}
        if tool_choice == "none":
            return {"functionCallingConfig": {"mode": "NONE"}}
    if isinstance(tool_choice, dict):
        fn = tool_choice.get("function") or {}
        name = fn.get("name")
        if name:
            return {
                "functionCallingConfig": {
                    "mode": "ANY",
                    "allowedFunctionNames": [str(name)],
                },
            }
    return None


def _normalize_thinking_config(config: Any) -> Optional[Dict[str, Any]]:
    """Accept thinkingBudget / thinkingLevel / includeThoughts (+ snake_case)."""
    if not isinstance(config, dict) or not config:
        return None
    budget = config.get("thinkingBudget", config.get("thinking_budget"))
    level = config.get("thinkingLevel", config.get("thinking_level"))
    include = config.get("includeThoughts", config.get("include_thoughts"))
    normalized: Dict[str, Any] = {}
    if isinstance(budget, (int, float)):
        normalized["thinkingBudget"] = int(budget)
    if isinstance(level, str) and level.strip():
        normalized["thinkingLevel"] = level.strip().lower()
    if isinstance(include, bool):
        normalized["includeThoughts"] = include
    return normalized or None


def build_gemini_request(
    *,
    messages: List[Dict[str, Any]],
    tools: Any = None,
    tool_choice: Any = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    top_p: Optional[float] = None,
    stop: Any = None,
    thinking_config: Any = None,
) -> Dict[str, Any]:
    """Build the inner Gemini request body (goes inside ``request`` wrapper)."""
    contents, system_instruction = _build_gemini_contents(messages)

    body: Dict[str, Any] = {"contents": contents}
    if system_instruction is not None:
        body["systemInstruction"] = system_instruction

    gemini_tools = _translate_tools_to_gemini(tools)
    if gemini_tools:
        body["tools"] = gemini_tools
    tool_cfg = _translate_tool_choice_to_gemini(tool_choice)
    if tool_cfg is not None:
        body["toolConfig"] = tool_cfg

    generation_config: Dict[str, Any] = {}
    if isinstance(temperature, (int, float)):
        generation_config["temperature"] = float(temperature)
    if isinstance(max_tokens, int) and max_tokens > 0:
        generation_config["maxOutputTokens"] = max_tokens
    if isinstance(top_p, (int, float)):
        generation_config["topP"] = float(top_p)
    if isinstance(stop, str) and stop:
        generation_config["stopSequences"] = [stop]
    elif isinstance(stop, list) and stop:
        generation_config["stopSequences"] = [str(s) for s in stop if s]
    normalized_thinking = _normalize_thinking_config(thinking_config)
    if normalized_thinking:
        generation_config["thinkingConfig"] = normalized_thinking
    if generation_config:
        body["generationConfig"] = generation_config

    return body


def wrap_code_assist_request(
    *,
    project_id: str,
    model: str,
    inner_request: Dict[str, Any],
    user_prompt_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrap the inner Gemini request in the Code Assist envelope."""
    return {
        "project": project_id,
        "model": model,
        "user_prompt_id": user_prompt_id or str(uuid.uuid4()),
        "request": inner_request,
    }


# =============================================================================
# Response translation: Gemini → OpenAI
# =============================================================================


def _translate_gemini_response(
    resp: Dict[str, Any],
    model: str,
) -> SimpleNamespace:
    """Non-streaming Gemini response -> OpenAI-shaped SimpleNamespace.

    Code Assist wraps the actual Gemini response inside ``response``, so we
    unwrap it first if present.
    """
    inner = resp.get("response") if isinstance(resp.get("response"), dict) else resp

    candidates = inner.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return _empty_response(
            model,
            diagnostic=_build_gemini_diagnostic(inner, None),
        )

    cand = candidates[0] if isinstance(candidates[0], dict) else {}
    diagnostic = _build_gemini_diagnostic(inner, cand)
    content_obj = cand.get("content") if isinstance(cand, dict) else {}
    parts = content_obj.get("parts") if isinstance(content_obj, dict) else []

    text_pieces: List[str] = []
    reasoning_pieces: List[str] = []
    tool_calls: List[SimpleNamespace] = []
    invalid_tool_batch = False

    for i, part in enumerate(parts or []):
        if not isinstance(part, dict):
            continue
        parsed_call, malformed_call = _parse_gemini_function_call(part)
        if malformed_call:
            invalid_tool_batch = True
        # Thought parts are model's internal reasoning — surface as reasoning,
        # don't mix into content.
        if part.get("thought") is True:
            if isinstance(part.get("text"), str):
                reasoning_pieces.append(part["text"])
        elif isinstance(part.get("text"), str):
            text_pieces.append(part["text"])
        if parsed_call is not None:
            name, args_str = parsed_call
            tool_calls.append(
                SimpleNamespace(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    type="function",
                    index=i,
                    function=SimpleNamespace(name=name, arguments=args_str),
                )
            )

    mapped_finish_reason = _map_gemini_finish_reason(
        str(cand.get("finishReason") or "")
    )
    if invalid_tool_batch:
        mapped_finish_reason = "error"
        diagnostic = dict(diagnostic)
        diagnostic["finish_reason"] = "INVALID"
    accepted_content = (
        not invalid_tool_batch
        and diagnostic["prompt_block_reason"] == "UNSPECIFIED"
        and diagnostic["finish_reason"] in {"STOP", "MAX_TOKENS"}
    )
    if not accepted_content:
        # Google may include partial content alongside a filtered or otherwise
        # abnormal terminal reason. Nothing from a rejected candidate is safe
        # to display or execute.
        text_pieces = []
        reasoning_pieces = []
        tool_calls = []
    elif mapped_finish_reason != "stop":
        # A truncated response is text-only; an incomplete function call must
        # never be dispatched as though it were complete.
        tool_calls = []
    finish_reason = "tool_calls" if tool_calls else mapped_finish_reason

    usage_meta = inner.get("usageMetadata") or {}
    usage = SimpleNamespace(
        prompt_tokens=int(usage_meta.get("promptTokenCount") or 0),
        completion_tokens=int(usage_meta.get("candidatesTokenCount") or 0),
        total_tokens=int(usage_meta.get("totalTokenCount") or 0),
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=int(usage_meta.get("cachedContentTokenCount") or 0),
        ),
    )

    message = SimpleNamespace(
        role="assistant",
        content="".join(text_pieces) if text_pieces else None,
        tool_calls=tool_calls or None,
        reasoning="".join(reasoning_pieces) or None,
        reasoning_content="".join(reasoning_pieces) or None,
        reasoning_details=None,
    )
    choice = SimpleNamespace(
        index=0,
        message=message,
        finish_reason=finish_reason,
    )
    return SimpleNamespace(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=usage,
        _elevate_gemini_diagnostic=diagnostic,
    )


def _empty_response(
    model: str,
    *,
    diagnostic: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    message = SimpleNamespace(
        role="assistant",
        content="",
        tool_calls=None,
        reasoning=None,
        reasoning_content=None,
        reasoning_details=None,
    )
    choice = SimpleNamespace(index=0, message=message, finish_reason="stop")
    diagnostic = diagnostic or {}
    usage = SimpleNamespace(
        prompt_tokens=_gemini_diagnostic_count(diagnostic.get("prompt_tokens")),
        completion_tokens=_gemini_diagnostic_count(diagnostic.get("candidate_tokens")),
        total_tokens=_gemini_diagnostic_count(diagnostic.get("total_tokens")),
        prompt_tokens_details=SimpleNamespace(
            cached_tokens=_gemini_diagnostic_count(diagnostic.get("cached_tokens"))
        ),
    )
    return SimpleNamespace(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        object="chat.completion",
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=usage,
        _elevate_gemini_diagnostic=diagnostic,
    )


# =============================================================================
# Streaming SSE iterator
# =============================================================================


class _GeminiStreamChunk(SimpleNamespace):
    """Mimics an OpenAI ChatCompletionChunk with .choices[0].delta."""

    pass


def _make_stream_chunk(
    *,
    model: str,
    content: str = "",
    tool_call_delta: Optional[Dict[str, Any]] = None,
    finish_reason: Optional[str] = None,
    reasoning: str = "",
) -> _GeminiStreamChunk:
    delta_kwargs: Dict[str, Any] = {
        "role": "assistant",
        "content": None,
        "tool_calls": None,
        "reasoning": None,
        "reasoning_content": None,
    }
    if content:
        delta_kwargs["content"] = content
    if tool_call_delta is not None:
        delta_kwargs["tool_calls"] = [
            SimpleNamespace(
                index=tool_call_delta.get("index", 0),
                id=tool_call_delta.get("id") or f"call_{uuid.uuid4().hex[:12]}",
                type="function",
                function=SimpleNamespace(
                    name=tool_call_delta.get("name") or "",
                    arguments=tool_call_delta.get("arguments") or "",
                ),
            )
        ]
    if reasoning:
        delta_kwargs["reasoning"] = reasoning
        delta_kwargs["reasoning_content"] = reasoning
    delta = SimpleNamespace(**delta_kwargs)
    choice = SimpleNamespace(index=0, delta=delta, finish_reason=finish_reason)
    return _GeminiStreamChunk(
        id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
        object="chat.completion.chunk",
        created=int(time.time()),
        model=model,
        choices=[choice],
        usage=None,
    )


def _iter_sse_events(response: httpx.Response) -> Iterator[Dict[str, Any]]:
    """Parse Server-Sent Events from an httpx streaming response."""
    buffer = ""
    for chunk in response.iter_text():
        if not chunk:
            continue
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")
            if not line:
                continue
            if line.startswith("data: "):
                data = line[6:]
                if data == "[DONE]":
                    return
                try:
                    payload = json.loads(data)
                except json.JSONDecodeError as exc:
                    logger.debug(
                        "Non-JSON Gemini SSE line (chars=%d, error=%s)",
                        len(data),
                        type(exc).__name__,
                    )
                    continue
                if isinstance(payload, dict):
                    yield payload


def _translate_stream_event(
    event: Dict[str, Any],
    model: str,
    tool_call_counter: List[int],
) -> List[_GeminiStreamChunk]:
    """Unwrap Code Assist envelope and emit OpenAI-shaped chunk(s).

    ``tool_call_counter`` is mutable stream state. Its first element is the
    next call index; an optional second element records whether a malformed
    call poisoned the parallel batch and whether its terminal error was
    emitted. Each valid ``functionCall`` part gets a fresh, unique OpenAI
    ``index`` — keying by function name would collide whenever the model
    issues parallel calls to the same tool (e.g. reading three files in one
    turn).
    """
    if _stream_tool_batch_state(tool_call_counter) == (
        _STREAM_TOOL_BATCH_ERROR_EMITTED
    ):
        return []

    inner = event.get("response") if isinstance(event.get("response"), dict) else event
    candidates = inner.get("candidates") or []
    if not candidates:
        diagnostic = _build_gemini_diagnostic(inner, None)
        usage_meta = inner.get("usageMetadata") or {}
        prompt_blocked = diagnostic["prompt_block_reason"] != "UNSPECIFIED"
        if not prompt_blocked and not usage_meta:
            return []
        diagnostic_chunk = _GeminiStreamChunk(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            object="chat.completion.chunk",
            created=int(time.time()),
            model=model,
            choices=[],
            usage=None,
        )
        if prompt_blocked:
            diagnostic_chunk._elevate_gemini_diagnostic = diagnostic
        if isinstance(usage_meta, dict) and usage_meta:
            diagnostic_chunk.usage = SimpleNamespace(
                prompt_tokens=_gemini_diagnostic_count(
                    usage_meta.get("promptTokenCount")
                ),
                completion_tokens=_gemini_diagnostic_count(
                    usage_meta.get("candidatesTokenCount")
                ),
                total_tokens=_gemini_diagnostic_count(
                    usage_meta.get("totalTokenCount")
                ),
                prompt_tokens_details=SimpleNamespace(
                    cached_tokens=_gemini_diagnostic_count(
                        usage_meta.get("cachedContentTokenCount")
                    ),
                ),
            )
        return [diagnostic_chunk]
    cand = candidates[0] if isinstance(candidates[0], dict) else {}

    chunks: List[_GeminiStreamChunk] = []

    content = cand.get("content") or {}
    parts = content.get("parts") if isinstance(content, dict) else []
    if not isinstance(parts, list):
        parts = []
    finish_reason_value = cand.get("finishReason")
    finish_reason_present = "finishReason" in cand
    finish_reason_raw = str(finish_reason_value) if finish_reason_present else ""
    mapped_finish_reason = (
        _map_gemini_finish_reason(finish_reason_raw) if finish_reason_present else None
    )
    event_diagnostic = _build_gemini_diagnostic(inner, cand)

    parsed_calls: Dict[int, tuple[str, str]] = {}
    invalid_tool_batch = (
        _stream_tool_batch_state(tool_call_counter) == _STREAM_TOOL_BATCH_INVALID
    )
    if not invalid_tool_batch:
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            parsed_call, malformed_call = _parse_gemini_function_call(part)
            if malformed_call:
                _poison_stream_tool_batch(tool_call_counter)
                invalid_tool_batch = True
                break
            if parsed_call is not None:
                parsed_calls[part_index] = parsed_call
    if invalid_tool_batch:
        # Reject the complete batch before emitting any sibling. The error is
        # terminal even when the malformed part arrives before Gemini's normal
        # finish event; later events are suppressed by the persisted marker.
        finish_reason_present = True
        mapped_finish_reason = "error"
        event_diagnostic = dict(event_diagnostic)
        event_diagnostic["finish_reason"] = "INVALID"

    event_content_accepted = (
        not invalid_tool_batch
        and event_diagnostic["prompt_block_reason"] == "UNSPECIFIED"
        and (
            not finish_reason_present
            or event_diagnostic["finish_reason"] in {"STOP", "MAX_TOKENS"}
        )
    )
    for part_index, part in enumerate(parts if event_content_accepted else []):
        if not isinstance(part, dict):
            continue
        if part.get("thought") is True and isinstance(part.get("text"), str):
            chunks.append(
                _make_stream_chunk(
                    model=model,
                    reasoning=part["text"],
                )
            )
            continue
        if isinstance(part.get("text"), str) and part["text"]:
            chunks.append(_make_stream_chunk(model=model, content=part["text"]))
        parsed_call = parsed_calls.get(part_index)
        if parsed_call is not None and mapped_finish_reason in {None, "stop"}:
            name, args_str = parsed_call
            idx = tool_call_counter[0]
            tool_call_counter[0] += 1
            chunks.append(
                _make_stream_chunk(
                    model=model,
                    tool_call_delta={
                        "index": idx,
                        "name": name,
                        "arguments": args_str,
                    },
                )
            )

    if finish_reason_present:
        mapped = (
            "tool_calls"
            if (
                not invalid_tool_batch
                and tool_call_counter[0] > 0
                and mapped_finish_reason == "stop"
            )
            else mapped_finish_reason
        )
        finish_chunk = _make_stream_chunk(
            model=model,
            finish_reason=mapped,
        )
        finish_chunk._elevate_gemini_diagnostic = event_diagnostic
        usage_meta = inner.get("usageMetadata") or {}
        if isinstance(usage_meta, dict) and usage_meta:
            finish_chunk.usage = SimpleNamespace(
                prompt_tokens=_gemini_diagnostic_count(
                    usage_meta.get("promptTokenCount")
                ),
                completion_tokens=_gemini_diagnostic_count(
                    usage_meta.get("candidatesTokenCount")
                ),
                total_tokens=_gemini_diagnostic_count(
                    usage_meta.get("totalTokenCount")
                ),
                prompt_tokens_details=SimpleNamespace(
                    cached_tokens=_gemini_diagnostic_count(
                        usage_meta.get("cachedContentTokenCount")
                    ),
                ),
            )
        chunks.append(finish_chunk)
        if invalid_tool_batch:
            tool_call_counter[1] = _STREAM_TOOL_BATCH_ERROR_EMITTED
    return chunks


# =============================================================================
# GeminiCloudCodeClient — OpenAI-compatible facade
# =============================================================================

MARKER_BASE_URL = "cloudcode-pa://google"


class _GeminiChatCompletions:
    def __init__(self, client: "GeminiCloudCodeClient"):
        self._client = client

    def create(self, **kwargs: Any) -> Any:
        return self._client._create_chat_completion(**kwargs)


class _GeminiChatNamespace:
    def __init__(self, client: "GeminiCloudCodeClient"):
        self.completions = _GeminiChatCompletions(client)


class GeminiCloudCodeClient:
    """Minimal OpenAI-SDK-compatible facade over Code Assist v1internal."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        default_headers: Optional[Dict[str, str]] = None,
        project_id: str = "",
        timeout: Any = None,
        **_: Any,
    ):
        # `api_key` here is a dummy — real auth is the OAuth access token
        # fetched on every call via agent.google_oauth.get_valid_access_token().
        # We accept the kwarg for openai.OpenAI interface parity.
        self.api_key = api_key or "google-oauth"
        self.base_url = base_url or MARKER_BASE_URL
        self._default_headers = dict(default_headers or {})
        self._configured_project_id = project_id
        self._project_context: Optional[ProjectContext] = None
        self._project_context_lock = False  # simple single-thread guard
        self.chat = _GeminiChatNamespace(self)
        self.is_closed = False
        default_timeout = httpx.Timeout(
            connect=15.0,
            read=600.0,
            write=30.0,
            pool=30.0,
        )
        self._http = httpx.Client(timeout=timeout or default_timeout)

    def close(self) -> None:
        self.is_closed = True
        try:
            self._http.close()
        except Exception:
            pass

    # Implement the OpenAI SDK's context-manager-ish closure check
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _ensure_project_context(self, access_token: str, model: str) -> ProjectContext:
        """Lazily resolve and cache the project context for this client."""
        if self._project_context is not None:
            return self._project_context

        env_project = google_oauth.resolve_project_id_from_env()
        creds = google_oauth.load_credentials()
        stored_project = creds.project_id if creds else ""

        # Prefer what's already baked into the creds
        if stored_project:
            self._project_context = ProjectContext(
                project_id=stored_project,
                managed_project_id=creds.managed_project_id if creds else "",
                tier_id="",
                source="stored",
            )
            return self._project_context

        ctx = resolve_project_context(
            access_token,
            configured_project_id=self._configured_project_id,
            env_project_id=env_project,
            user_agent_model=model,
        )
        # Persist discovered project back to the creds file so the next
        # session doesn't re-run the discovery.
        if ctx.project_id or ctx.managed_project_id:
            google_oauth.update_project_ids(
                project_id=ctx.project_id,
                managed_project_id=ctx.managed_project_id,
            )
        self._project_context = ctx
        return ctx

    def _create_chat_completion(
        self,
        *,
        model: str = "gemini-2.5-flash",
        messages: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        tools: Any = None,
        tool_choice: Any = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        stop: Any = None,
        extra_body: Optional[Dict[str, Any]] = None,
        timeout: Any = None,
        **_: Any,
    ) -> Any:
        access_token = google_oauth.get_valid_access_token()
        ctx = self._ensure_project_context(access_token, model)

        thinking_config = None
        if isinstance(extra_body, dict):
            thinking_config = extra_body.get("thinking_config") or extra_body.get(
                "thinkingConfig"
            )

        inner = build_gemini_request(
            messages=messages or [],
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            stop=stop,
            thinking_config=thinking_config,
        )
        wrapped = wrap_code_assist_request(
            project_id=ctx.project_id,
            model=model,
            inner_request=inner,
        )

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "elevate-agent (gemini-cli-compat)",
            "X-Goog-Api-Client": "gl-python/elevate",
            "x-activity-request-id": str(uuid.uuid4()),
        }
        headers.update(self._default_headers)

        if stream:
            return self._stream_completion(
                model=model,
                wrapped=wrapped,
                headers=headers,
                timeout=timeout,
            )

        url = f"{CODE_ASSIST_ENDPOINT}/v1internal:generateContent"
        request_kwargs: Dict[str, Any] = {
            "json": wrapped,
            "headers": headers,
        }
        if timeout is not None:
            request_kwargs["timeout"] = timeout
        response = self._http.post(url, **request_kwargs)
        if response.status_code != 200:
            raise _gemini_http_error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CodeAssistError(
                f"Invalid JSON from Code Assist: {exc}",
                code="code_assist_invalid_json",
            ) from exc
        return _translate_gemini_response(payload, model=model)

    def _stream_completion(
        self,
        *,
        model: str,
        wrapped: Dict[str, Any],
        headers: Dict[str, str],
        timeout: Any = None,
    ) -> Iterator[_GeminiStreamChunk]:
        """Generator that yields OpenAI-shaped streaming chunks."""
        url = f"{CODE_ASSIST_ENDPOINT}/v1internal:streamGenerateContent?alt=sse"
        stream_headers = dict(headers)
        stream_headers["Accept"] = "text/event-stream"

        def _generator() -> Iterator[_GeminiStreamChunk]:
            try:
                request_kwargs: Dict[str, Any] = {
                    "json": wrapped,
                    "headers": stream_headers,
                }
                if timeout is not None:
                    request_kwargs["timeout"] = timeout
                with self._http.stream(
                    "POST",
                    url,
                    **request_kwargs,
                ) as response:
                    if response.status_code != 200:
                        # Materialize error body for better diagnostics
                        response.read()
                        raise _gemini_http_error(response)
                    tool_call_counter: List[int] = [0]
                    for event in _iter_sse_events(response):
                        for chunk in _translate_stream_event(
                            event, model, tool_call_counter
                        ):
                            yield chunk
            except httpx.HTTPError as exc:
                raise CodeAssistError(
                    f"Streaming request failed: {exc}",
                    code="code_assist_stream_error",
                ) from exc

        return _generator()


def _gemini_http_error(response: httpx.Response) -> CodeAssistError:
    """Translate an httpx response into a CodeAssistError with rich metadata.

    Parses Google's error envelope (``{"error": {"code", "message", "status",
    "details": [...]}}``) so the agent's error classifier can reason about
    the failure — ``status_code`` enables the rate_limit / auth classification
    paths, and ``response`` lets the main loop honor ``Retry-After`` just
    like it does for OpenAI SDK exceptions.

    Also lifts a few recognizable Google conditions into human-readable
    messages so the user sees something better than a 500-char JSON dump:

        MODEL_CAPACITY_EXHAUSTED → "Gemini model capacity exhausted for
            <model>. This is a Google-side throttle..."
        RESOURCE_EXHAUSTED w/o reason → quota-style message
        404 → "Model <name> not found at cloudcode-pa..."
    """
    status = response.status_code

    # Parse the body once, surviving any weird encodings.
    body_text = ""
    body_json: Dict[str, Any] = {}
    try:
        body_text = response.text
    except Exception:
        body_text = ""
    if body_text:
        try:
            parsed = json.loads(body_text)
            if isinstance(parsed, dict):
                body_json = parsed
        except (ValueError, TypeError):
            body_json = {}

    # Dig into Google's error envelope.  Shape is:
    #   {"error": {"code": 429, "message": "...", "status": "RESOURCE_EXHAUSTED",
    #              "details": [{"@type": ".../ErrorInfo", "reason": "MODEL_CAPACITY_EXHAUSTED",
    #                           "metadata": {...}},
    #                          {"@type": ".../RetryInfo", "retryDelay": "30s"}]}}
    err_obj = body_json.get("error") if isinstance(body_json, dict) else None
    if not isinstance(err_obj, dict):
        err_obj = {}
    err_status = str(err_obj.get("status") or "").strip()
    err_message = str(err_obj.get("message") or "").strip()
    _raw_details = err_obj.get("details")
    err_details_list = _raw_details if isinstance(_raw_details, list) else []

    # Extract google.rpc.ErrorInfo reason + metadata.  There may be more
    # than one ErrorInfo (rare), so we pick the first one with a reason.
    error_reason = ""
    error_metadata: Dict[str, Any] = {}
    retry_delay_seconds: Optional[float] = None
    for detail in err_details_list:
        if not isinstance(detail, dict):
            continue
        type_url = str(detail.get("@type") or "")
        if not error_reason and type_url.endswith("/google.rpc.ErrorInfo"):
            reason = detail.get("reason")
            if isinstance(reason, str) and reason:
                error_reason = reason
            md = detail.get("metadata")
            if isinstance(md, dict):
                error_metadata = md
        elif retry_delay_seconds is None and type_url.endswith("/google.rpc.RetryInfo"):
            # retryDelay is a google.protobuf.Duration string like "30s" or "1.5s".
            delay_raw = detail.get("retryDelay")
            if isinstance(delay_raw, str) and delay_raw.endswith("s"):
                try:
                    retry_delay_seconds = float(delay_raw[:-1])
                except ValueError:
                    pass
            elif isinstance(delay_raw, (int, float)):
                retry_delay_seconds = float(delay_raw)

    # Fall back to the Retry-After header if the body didn't include RetryInfo.
    if retry_delay_seconds is None:
        try:
            header_val = response.headers.get("Retry-After") or response.headers.get(
                "retry-after"
            )
        except Exception:
            header_val = None
        if header_val:
            try:
                retry_delay_seconds = float(header_val)
            except (TypeError, ValueError):
                retry_delay_seconds = None

    # Classify the error code.  ``code_assist_rate_limited`` stays the default
    # for 429s; a more specific reason tag helps downstream callers (e.g. tests,
    # logs) without changing the rate_limit classification path.
    code = f"code_assist_http_{status}"
    if status == 401:
        code = "code_assist_unauthorized"
    elif status == 429:
        code = "code_assist_rate_limited"
        if error_reason == "MODEL_CAPACITY_EXHAUSTED":
            code = "code_assist_capacity_exhausted"

    # Build a human-readable message.  Keep the status + a raw-body tail for
    # debugging, but lead with a friendlier summary when we recognize the
    # Google signal.
    model_hint = ""
    if isinstance(error_metadata, dict):
        model_hint = str(
            error_metadata.get("model") or error_metadata.get("modelId") or ""
        ).strip()

    if status == 429 and error_reason == "MODEL_CAPACITY_EXHAUSTED":
        target = model_hint or "this Gemini model"
        message = (
            f"Gemini capacity exhausted for {target} (Google-side throttle, "
            f"not a Elevate issue). Try a different Gemini model or set a "
            f"fallback_providers entry to a non-Gemini provider."
        )
        if retry_delay_seconds is not None:
            message += f" Google suggests retrying in {retry_delay_seconds:g}s."
    elif status == 429 and err_status == "RESOURCE_EXHAUSTED":
        message = (
            f"Gemini quota exhausted ({err_message or 'RESOURCE_EXHAUSTED'}). "
            f"Check /gquota for remaining daily requests."
        )
        if retry_delay_seconds is not None:
            message += f" Retry suggested in {retry_delay_seconds:g}s."
    elif status == 404:
        # Google returns 404 when a model has been retired or renamed.
        target = model_hint or (err_message or "model")
        message = (
            f"Code Assist 404: {target} is not available at "
            f"cloudcode-pa.googleapis.com. It may have been renamed or "
            f"retired. Check elevate_cli/models.py for the current list."
        )
    elif err_message:
        # Generic fallback with the parsed message.
        message = f"Code Assist HTTP {status} ({err_status or 'error'}): {err_message}"
    else:
        # Last-ditch fallback — raw body snippet.
        message = f"Code Assist returned HTTP {status}: {body_text[:500]}"

    return CodeAssistError(
        message,
        code=code,
        status_code=status,
        response=response,
        retry_after=retry_delay_seconds,
        details={
            "status": err_status,
            "reason": error_reason,
            "metadata": error_metadata,
            "message": err_message,
        },
    )
