"""OpenAI-shaped client backed by the local Claude Code CLI.

This is a pragmatic bridge for machines where `claude -p` works but native
Anthropic third-party OAuth is blocked by extra-usage billing.  It intentionally
implements the small Chat Completions surface Elevate needs for plain text
turns: client.chat.completions.create(...). Tool calling is not supported in
this first pass; if tools are provided, the wrapper still asks Claude to answer
normally rather than emitting structured tool calls.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from types import SimpleNamespace
from typing import Any, Iterable


class ClaudeCodeCLIClient:
    """Minimal OpenAI-compatible chat client that shells out to Claude Code."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None,
                 command: str | None = None, args: list[str] | None = None,
                 timeout: float | None = None, **_: Any) -> None:
        self.api_key = api_key or "claude-code-cli"
        self.base_url = base_url or "claude-code-cli://local"
        self.command = command or os.getenv("ELEVATE_CLAUDE_CODE_COMMAND", "claude")
        self.args = list(args or [])
        self.timeout = float(timeout or os.getenv("ELEVATE_CLAUDE_CODE_TIMEOUT", "900"))
        self.chat = SimpleNamespace(completions=_ClaudeCodeCompletions(self))

    def close(self) -> None:  # OpenAI client compatibility
        return None


class _ClaudeCodeCompletions:
    def __init__(self, parent: ClaudeCodeCLIClient) -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> Any:
        model = kwargs.get("model") or "sonnet"
        messages = kwargs.get("messages") or []
        timeout_arg = kwargs.get("timeout")
        timeout = timeout_arg if isinstance(timeout_arg, (int, float, str)) else self._parent.timeout
        prompt = _messages_to_prompt(messages, kwargs.get("tools"))
        stream = bool(kwargs.get("stream"))

        command_path = shutil.which(self._parent.command)
        if not command_path:
            raise RuntimeError(
                f"Claude Code CLI not found: {self._parent.command!r}. Install/login with `claude`."
            )

        cmd = [
            command_path,
            "-p",
            prompt,
            "--model",
            str(model),
            "--output-format",
            "text",
            "--no-session-persistence",
            *self._parent.args,
        ]
        proc = subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=float(timeout),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "Claude Code CLI failed").strip()
            raise RuntimeError(detail)

        content = proc.stdout.strip()
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=content, tool_calls=None),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
        )
        if stream:
            return _as_single_chunk_stream(content)
        return response


def _messages_to_prompt(messages: Iterable[dict[str, Any]], tools: Any = None) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = _clip(_stringify_content(msg.get("content", "")))
        if not content and msg.get("tool_calls"):
            content = "[assistant requested tool calls]"
        if role == "system":
            parts.append(f"System instructions:\n{content}")
        elif role == "tool":
            name = msg.get("name") or msg.get("tool_call_id") or "tool"
            parts.append(f"Tool result ({name}):\n{content}")
        else:
            parts.append(f"{role.title()}:\n{content}")

    if tools:
        parts.append(
            "Note: Elevate's Claude Code CLI bridge is running in plain-text mode. "
            "Do not attempt structured tool calls; answer directly from the provided context."
        )

    return "\n\n---\n\n".join(p for p in parts if p).strip() or "Hello"


def _clip(text: str, limit: int = 12000) -> str:
    """Keep Claude CLI bridge prompts lightweight and biased to the latest ask."""
    if len(text) <= limit:
        return text
    head = text[:2500]
    tail = text[-(limit - 2500):]
    return f"{head}\n\n[...middle clipped by Claude Code CLI bridge...]\n\n{tail}"


def _as_single_chunk_stream(content: str):
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=content,
                    tool_calls=None,
                    reasoning=None,
                    reasoning_content=None,
                ),
                finish_reason=None,
            )
        ],
        usage=None,
    )
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(
                    content=None,
                    tool_calls=None,
                    reasoning=None,
                    reasoning_content=None,
                ),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0),
    )


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    chunks.append(str(item.get("text", "")))
                else:
                    chunks.append(json.dumps(item, ensure_ascii=False))
            else:
                chunks.append(str(item))
        return "\n".join(chunks)
    if content is None:
        return ""
    return str(content)
