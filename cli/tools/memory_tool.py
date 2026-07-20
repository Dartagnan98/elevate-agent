#!/usr/bin/env python3
"""
Memory Tool Module - Persistent Curated Memory

Provides bounded, file-backed memory that persists across sessions. Two stores:
  - MEMORY.md: agent's personal notes and observations (environment facts, project
    conventions, tool quirks, things learned)
  - USER.md: what the agent knows about the user (preferences, communication style,
    expectations, workflow habits)

Both are injected into the system prompt as a frozen snapshot at session start.
Mid-session writes update files on disk immediately (durable) but do NOT change
the system prompt -- this preserves the prefix cache for the entire session.
The snapshot refreshes on the next session start.

Entry delimiter: § (section sign). Entries can be multiline.
Character limits (not tokens) because char counts are model-independent.

Design:
- Single `memory` tool with action parameter: add, replace, remove, read
- replace/remove use short unique substring matching (not full text or IDs)
- Behavioral guidance lives in the tool schema description
- Frozen snapshot pattern: system prompt is stable, tool responses show live state
"""

import json
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from elevate_constants import get_elevate_home
from typing import Dict, Any, List, NamedTuple, Optional

from utils import atomic_replace
from tools.dispatch_companion import DispatchCompanion

# fcntl is Unix-only; on Windows use msvcrt for file locking
msvcrt = None
try:
    import fcntl
except ImportError:
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        pass

logger = logging.getLogger(__name__)

# Where memory files live — resolved dynamically so profile overrides
# (ELEVATE_HOME env var changes) are always respected.  The old module-level
# constant was cached at import time and could go stale if a profile switch
# happened after the first import.
def get_memory_dir() -> Path:
    """Return the profile-scoped memories directory."""
    return get_elevate_home() / "memories"

ENTRY_DELIMITER = "\n§\n"


# ---------------------------------------------------------------------------
# Memory content scanning — lightweight check for injection/exfiltration
# in content that gets injected into the system prompt.
# ---------------------------------------------------------------------------

_MEMORY_THREAT_PATTERNS = [
    # Prompt injection
    (r'ignore\s+(previous|all|above|prior)\s+instructions', "prompt_injection"),
    (r'you\s+are\s+now\s+', "role_hijack"),
    (r'do\s+not\s+tell\s+the\s+user', "deception_hide"),
    (r'system\s+prompt\s+override', "sys_prompt_override"),
    (r'disregard\s+(your|all|any)\s+(instructions|rules|guidelines)', "disregard_rules"),
    (r'act\s+as\s+(if|though)\s+you\s+(have\s+no|don\'t\s+have)\s+(restrictions|limits|rules)', "bypass_restrictions"),
    # Exfiltration via curl/wget with secrets
    (r'curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_curl"),
    (r'wget\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|API)', "exfil_wget"),
    (r'cat\s+[^\n]*(\.env|credentials|\.netrc|\.pgpass|\.npmrc|\.pypirc)', "read_secrets"),
    # Persistence via shell rc
    (r'authorized_keys', "ssh_backdoor"),
    (r'\$HOME/\.ssh|\~/\.ssh', "ssh_access"),
    (r'\$HOME/\.hermes/\.env|\~/\.hermes/\.env', "hermes_env"),
]

# Subset of invisible chars for injection detection
_INVISIBLE_CHARS = {
    '\u200b', '\u200c', '\u200d', '\u2060', '\ufeff',
    '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
}


def _durability_warning(content: str) -> Optional[str]:
    """Non-blocking durability check for explicit memory saves.

    The memory tool is an explicit, user/agent-initiated save path, so the
    holographic durability gate is downgraded to a warning here — the entry
    is always saved (user intent wins), but task-shaped/ephemeral content
    gets flagged so the agent can reconsider. Never raises; returns None when
    the classifier is unavailable or the content looks durable.
    """
    try:
        from plugins.memory.holographic.quality import classify_fact_durability
    except Exception:
        return None
    try:
        result = classify_fact_durability(content)
    except Exception:
        return None
    if result.get("durability") == "ephemeral":
        return (
            "This entry looks ephemeral (one-off task chatter, confidence "
            f"{result.get('confidence')}). Saved anyway because this was an explicit save, "
            "but consider removing it when the task is done — memory is for durable facts."
        )
    return None


def _scan_memory_content(content: str) -> Optional[str]:
    """Scan memory content for injection/exfil patterns. Returns error string if blocked."""
    # Check invisible unicode
    for char in _INVISIBLE_CHARS:
        if char in content:
            return f"Blocked: content contains invisible unicode character U+{ord(char):04X} (possible injection)."

    # Check threat patterns
    for pattern, pid in _MEMORY_THREAT_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            return f"Blocked: content matches threat pattern '{pid}'. Memory entries are injected into the system prompt and must not contain injection or exfiltration payloads."

    return None


class MemoryStore:
    """
    Bounded curated memory with file persistence. One instance per AIAgent.

    Maintains two parallel states:
      - _system_prompt_snapshot: frozen at load time, used for system prompt injection.
        Never mutated mid-session. Keeps prefix cache stable.
      - memory_entries / user_entries: live state, mutated by tool calls, persisted to disk.
        Tool responses always reflect this live state.
    """

    def __init__(self, memory_char_limit: int = 2200, user_char_limit: int = 1375):
        self.memory_entries: List[str] = []
        self.user_entries: List[str] = []
        self.memory_char_limit = memory_char_limit
        self.user_char_limit = user_char_limit
        # Frozen snapshot for system prompt -- set once at load_from_disk()
        self._system_prompt_snapshot: Dict[str, str] = {"memory": "", "user": ""}

    def load_from_disk(self):
        """Load entries from MEMORY.md and USER.md, capture system prompt snapshot."""
        mem_dir = get_memory_dir()
        mem_dir.mkdir(parents=True, exist_ok=True)

        self.memory_entries = self._read_file(mem_dir / "MEMORY.md")
        self.user_entries = self._read_file(mem_dir / "USER.md")

        # Deduplicate entries (preserves order, keeps first occurrence)
        self.memory_entries = list(dict.fromkeys(self.memory_entries))
        self.user_entries = list(dict.fromkeys(self.user_entries))

        # Capture frozen snapshot for system prompt injection
        self._system_prompt_snapshot = {
            "memory": self._render_block("memory", self.memory_entries),
            "user": self._render_block("user", self.user_entries),
        }

    @staticmethod
    @contextmanager
    def _file_lock(path: Path):
        """Acquire an exclusive file lock for read-modify-write safety.

        Uses a separate .lock file so the memory file itself can still be
        atomically replaced via os.replace().
        """
        lock_path = path.with_suffix(path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)

        if fcntl is None and msvcrt is None:
            yield
            return

        fd = open(lock_path, "a+", encoding="utf-8")
        try:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_EX)
            else:
                fd.seek(0)
                msvcrt.locking(fd.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            if fcntl:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except (OSError, IOError):
                    pass
            elif msvcrt:
                try:
                    fd.seek(0)
                    msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
                except (OSError, IOError):
                    pass
            fd.close()

    @staticmethod
    def _path_for(target: str) -> Path:
        mem_dir = get_memory_dir()
        if target == "user":
            return mem_dir / "USER.md"
        return mem_dir / "MEMORY.md"

    def _reload_target(self, target: str):
        """Re-read entries from disk into in-memory state.

        Called under file lock to get the latest state before mutating.
        """
        fresh = self._read_file(self._path_for(target))
        fresh = list(dict.fromkeys(fresh))  # deduplicate
        self._set_entries(target, fresh)

    def save_to_disk(self, target: str):
        """Persist entries to the appropriate file. Called after every mutation."""
        get_memory_dir().mkdir(parents=True, exist_ok=True)
        self._write_file(self._path_for(target), self._entries_for(target))

    def _entries_for(self, target: str) -> List[str]:
        if target == "user":
            return self.user_entries
        return self.memory_entries

    def _set_entries(self, target: str, entries: List[str]):
        if target == "user":
            self.user_entries = entries
        else:
            self.memory_entries = entries

    def _char_count(self, target: str) -> int:
        entries = self._entries_for(target)
        if not entries:
            return 0
        return len(ENTRY_DELIMITER.join(entries))

    def _char_limit(self, target: str) -> int:
        if target == "user":
            return self.user_char_limit
        return self.memory_char_limit

    def add(self, target: str, content: str) -> Dict[str, Any]:
        """Append a new entry. Returns error if it would exceed the char limit."""
        content = content.strip()
        if not content:
            return {"success": False, "error": "Content cannot be empty."}

        # Scan for injection/exfiltration before accepting
        scan_error = _scan_memory_content(content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            # Re-read from disk under lock to pick up writes from other sessions
            self._reload_target(target)

            entries = self._entries_for(target)
            limit = self._char_limit(target)

            # Reject exact duplicates
            if content in entries:
                return self._success_response(target, "Entry already exists (no duplicate added).")

            # Calculate what the new total would be
            new_entries = entries + [content]
            new_total = len(ENTRY_DELIMITER.join(new_entries))

            if new_total > limit:
                current = self._char_count(target)
                return {
                    "success": False,
                    "error": (
                        f"Memory at {current:,}/{limit:,} chars. "
                        f"Adding this entry ({len(content)} chars) would exceed the limit. "
                        f"Replace or remove existing entries first."
                    ),
                    "current_entries": entries,
                    "usage": f"{current:,}/{limit:,}",
                }

            entries.append(content)
            self._set_entries(target, entries)
            self.save_to_disk(target)

        response = self._success_response(target, "Entry added.")
        warning = _durability_warning(content)
        if warning:
            response["durability_warning"] = warning
        return response

    def replace(self, target: str, old_text: str, new_content: str) -> Dict[str, Any]:
        """Find entry containing old_text substring, replace it with new_content."""
        old_text = old_text.strip()
        new_content = new_content.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}
        if not new_content:
            return {"success": False, "error": "new_content cannot be empty. Use 'remove' to delete entries."}

        # Scan replacement content for injection/exfiltration
        scan_error = _scan_memory_content(new_content)
        if scan_error:
            return {"success": False, "error": scan_error}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical (exact duplicates), operate on the first one
                unique_texts = {e for _, e in matches}
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                # All identical -- safe to replace just the first

            idx = matches[0][0]
            limit = self._char_limit(target)

            # Check that replacement doesn't blow the budget
            test_entries = entries.copy()
            test_entries[idx] = new_content
            new_total = len(ENTRY_DELIMITER.join(test_entries))

            if new_total > limit:
                return {
                    "success": False,
                    "error": (
                        f"Replacement would put memory at {new_total:,}/{limit:,} chars. "
                        f"Shorten the new content or remove other entries first."
                    ),
                }

            entries[idx] = new_content
            self._set_entries(target, entries)
            self.save_to_disk(target)

        return self._success_response(target, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> Dict[str, Any]:
        """Remove the entry containing old_text substring."""
        old_text = old_text.strip()
        if not old_text:
            return {"success": False, "error": "old_text cannot be empty."}

        with self._file_lock(self._path_for(target)):
            self._reload_target(target)

            entries = self._entries_for(target)
            matches = [(i, e) for i, e in enumerate(entries) if old_text in e]

            if not matches:
                return {"success": False, "error": f"No entry matched '{old_text}'."}

            if len(matches) > 1:
                # If all matches are identical (exact duplicates), remove the first one
                unique_texts = {e for _, e in matches}
                if len(unique_texts) > 1:
                    previews = [e[:80] + ("..." if len(e) > 80 else "") for _, e in matches]
                    return {
                        "success": False,
                        "error": f"Multiple entries matched '{old_text}'. Be more specific.",
                        "matches": previews,
                    }
                # All identical -- safe to remove just the first

            idx = matches[0][0]
            entries.pop(idx)
            self._set_entries(target, entries)
            self.save_to_disk(target)

        return self._success_response(target, "Entry removed.")

    def format_for_system_prompt(self, target: str) -> Optional[str]:
        """
        Return the frozen snapshot for system prompt injection.

        This returns the state captured at load_from_disk() time, NOT the live
        state. Mid-session writes do not affect this. This keeps the system
        prompt stable across all turns, preserving the prefix cache.

        Returns None if the snapshot is empty (no entries at load time).
        """
        block = self._system_prompt_snapshot.get(target, "")
        return block if block else None

    # -- Internal helpers --

    def _success_response(self, target: str, message: str = None) -> Dict[str, Any]:
        entries = self._entries_for(target)
        current = self._char_count(target)
        limit = self._char_limit(target)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        resp = {
            "success": True,
            "target": target,
            "entries": entries,
            "usage": f"{pct}% — {current:,}/{limit:,} chars",
            "entry_count": len(entries),
        }
        if message:
            resp["message"] = message
        return resp

    def _render_block(self, target: str, entries: List[str]) -> str:
        """Render a system prompt block with header and usage indicator."""
        if not entries:
            return ""

        limit = self._char_limit(target)
        content = ENTRY_DELIMITER.join(entries)
        current = len(content)
        pct = min(100, int((current / limit) * 100)) if limit > 0 else 0

        if target == "user":
            header = f"USER PROFILE (who the user is) [{pct}% — {current:,}/{limit:,} chars]"
        else:
            header = f"MEMORY (your personal notes) [{pct}% — {current:,}/{limit:,} chars]"

        separator = "═" * 46
        return f"{separator}\n{header}\n{separator}\n{content}"

    @staticmethod
    def _read_file(path: Path) -> List[str]:
        """Read a memory file and split into entries.

        No file locking needed: _write_file uses atomic rename, so readers
        always see either the previous complete file or the new complete file.
        """
        if not path.exists():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except (OSError, IOError):
            return []

        if not raw.strip():
            return []

        # Use ENTRY_DELIMITER for consistency with _write_file. Splitting by "§"
        # alone would incorrectly split entries that contain "§" in their content.
        entries = [e.strip() for e in raw.split(ENTRY_DELIMITER)]
        return [e for e in entries if e]

    @staticmethod
    def _write_file(path: Path, entries: List[str]):
        """Write entries to a memory file using atomic temp-file + rename.

        Previous implementation used open("w") + flock, but "w" truncates the
        file *before* the lock is acquired, creating a race window where
        concurrent readers see an empty file. Atomic rename avoids this:
        readers always see either the old complete file or the new one.
        """
        content = ENTRY_DELIMITER.join(entries) if entries else ""
        try:
            # Write to temp file in same directory (same filesystem for atomic rename)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".mem_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                atomic_replace(tmp_path, path)
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (OSError, IOError) as e:
            raise RuntimeError(f"Failed to write memory file {path}: {e}")


def memory_tool(
    action: str,
    target: str = "memory",
    content: str = None,
    old_text: str = None,
    store: Optional[MemoryStore] = None,
) -> str:
    """
    Single entry point for the memory tool. Dispatches to MemoryStore methods.

    Returns JSON string with results.
    """
    if store is None:
        return tool_error("Memory is not available. It may be disabled in config or this environment.", success=False)

    if target not in {"memory", "user"}:
        return tool_error(f"Invalid target '{target}'. Use 'memory' or 'user'.", success=False)

    if action == "add":
        if not content:
            return tool_error("Content is required for 'add' action.", success=False)
        result = store.add(target, content)

    elif action == "replace":
        if not old_text:
            return tool_error("old_text is required for 'replace' action.", success=False)
        if not content:
            return tool_error("content is required for 'replace' action.", success=False)
        result = store.replace(target, old_text, content)

    elif action == "remove":
        if not old_text:
            return tool_error("old_text is required for 'remove' action.", success=False)
        result = store.remove(target, old_text)

    else:
        return tool_error(f"Unknown action '{action}'. Use: add, replace, remove", success=False)

    return json.dumps(result, ensure_ascii=False)


def check_memory_requirements() -> bool:
    """Memory tool has no external requirements -- always available."""
    return True


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

MEMORY_SCHEMA = {
    "name": "memory",
    "description": (
        "Save durable information to persistent memory that survives across sessions. "
        "Memory is injected into future turns, so keep it compact and focused on facts "
        "that will still matter later.\n\n"
        "WHEN TO SAVE (do this proactively, don't wait to be asked):\n"
        "- User corrects you or says 'remember this' / 'don't do that again'\n"
        "- User shares a preference, habit, or personal detail (name, role, timezone, coding style)\n"
        "- You discover something about the environment (OS, installed tools, project structure)\n"
        "- You learn a convention, API quirk, or workflow specific to this user's setup\n"
        "- You identify a stable fact that will be useful again in future sessions\n\n"
        "PRIORITY: User preferences and corrections > environment facts > procedural knowledge. "
        "The most valuable memory prevents the user from having to repeat themselves.\n\n"
        "Do NOT save task progress, session outcomes, completed-work logs, or temporary TODO "
        "state to memory; use session_search to recall those from past transcripts.\n"
        "If you've discovered a new way to do something, solved a problem that could be "
        "necessary later, save it as a skill with the skill tool.\n\n"
        "TWO TARGETS:\n"
        "- 'user': who the user is -- name, role, preferences, communication style, pet peeves\n"
        "- 'memory': your notes -- environment facts, project conventions, tool quirks, lessons learned\n\n"
        "ACTIONS: add (new entry), replace (update existing -- old_text identifies it), "
        "remove (delete -- old_text identifies it).\n\n"
        "SKIP: trivial/obvious info, things easily re-discovered, raw data dumps, and temporary task state."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "replace", "remove"],
                "description": "The action to perform."
            },
            "target": {
                "type": "string",
                "enum": ["memory", "user"],
                "description": "Which memory store: 'memory' for personal notes, 'user' for user profile."
            },
            "content": {
                "type": "string",
                "description": "The entry content. Required for 'add' and 'replace'."
            },
            "old_text": {
                "type": "string",
                "description": "Short unique substring identifying the entry to replace or remove."
            },
        },
        "required": ["action", "target"],
    },
}


# --- Registry ---
from tools.registry import registry, tool_error

# ---------------------------------------------------------------------------
# Registry-routed built-in ``memory`` lane (ERB-406 step 4 / A2b lane 5)
#
# The agent loop historically dispatched the built-in ``memory`` tool straight
# into ``memory_tool(store=self._memory_store)`` and then fired the external
# provider bridge (``MemoryManager.on_memory_write``) inline in the branch,
# bypassing the atomic registry shadow boundary entirely.  This seam moves that
# lane onto the common adapter (``model_tools.dispatch_agent_owned_registry_tool``;
# per-lane recipe in ``elevate-a2b-migration-recipe-2026-07-17.md``) so every
# built-in memory write is captured with a frozen registration identity,
# canonical args digest, and accepted-turn policy context exactly like an
# ordinary registry tool.
#
# Process state — the per-agent ``MemoryStore`` (``self._memory_store``), the
# live ``MemoryManager`` (``self._memory_manager``) used for the provider
# bridge, and the caller-built bridge metadata — is on the AIAgent, not
# tool-call data, so it can never ride through the registry's JSON-frozen
# argument or handler-kwargs snapshot.  All three ride together through one
# dispatch-scoped :class:`~tools.dispatch_companion.DispatchCompanion` holding a
# small immutable binding struct; the registered handler resolves it EAGERLY at
# handler start and never stores it for a lazy read.  A caller that reaches the
# registered handler outside the binding (legacy ``registry.dispatch`` without
# an agent, plugin dispatch, hallucinated calls) sees ``None``, so the store is
# absent and ``memory_tool`` returns its long-standing "Memory is not available"
# typed error — byte-identical to the pre-migration lambda that read
# ``kw.get("store")`` (which was likewise ``None`` off the agent loop).
#
# Two traps preserved byte-identically (recipe lane notes):
#  1. ``_memory_policy_block`` (the agent's per-agent recall/write policy) stays
#     in the CALLER, exactly where and when each branch ran it today.  The four
#     agent-loop copies diverge on whether they apply that gate — the concurrent
#     and sequential ``run_agent`` branches do; the extracted
#     ``tool_executor``/``agent_runtime_helpers`` copies never did — so folding
#     it into the shared handler would silently ADD the gate to the copies that
#     lacked it.  Keeping it in the caller preserves each copy's exact behavior
#     while still running BEFORE any effect (the refusal short-circuits before
#     this wrapper is ever called).
#  2. The ``on_memory_write`` provider bridge is a hidden POST-result effect.
#     It moves INSIDE the registered handler (after the store write, same
#     swallow-exceptions semantics, same add/replace-only condition) so a
#     blocked / stale / denied dispatch — whose handler never starts — can never
#     fire it.  The bridge metadata differs per caller (an inline
#     ``{session_id, agent_id}`` dict vs the module-level
#     ``agent.background_review.build_memory_write_metadata(agent, …)``),
#     so each caller builds its own metadata under the SAME add/replace guard it
#     used before and passes it through the binding.
#
# Effect honesty (ERB-404 doctrine; declaration != allowance): every valid
# built-in memory action (add / replace / remove) writes local memory files,
# and the ``on_memory_write`` bridge reaches an arbitrary external provider
# whose effect surface is unproven (local for holographic, potentially remote
# for honcho/mem0/…).  No pure-read surface exists and the write floor cannot be
# honestly bounded, so the registration carries NO effect declaration
# (``effects=None`` -> UNKNOWN), matching the pre-migration state.  A restricted
# accepted-turn policy therefore fails closed on ``memory`` under exact Realtor
# Beta instead of assuming a bounded write.  ``memory`` is in
# ``model_tools._AGENT_LOOP_TOOLS`` — ``handle_function_call`` keeps refusing it
# (that guard stays; the adapter enters the registry directly, not via
# ``handle_function_call``).
# ---------------------------------------------------------------------------


class _MemoryToolBinding(NamedTuple):
    """One dispatch's worth of built-in ``memory`` process state.

    ``store`` is the per-agent :class:`MemoryStore` (may be ``None`` when memory
    is disabled — distinct from "no binding at all", which is why a struct is
    bound rather than the bare store).  ``manager`` is the live
    :class:`~agent.memory_manager.MemoryManager` (or ``None``) used for the
    provider bridge; ``metadata_factory`` is a caller-supplied zero-arg callable
    (or ``None``) that BUILDS the ``on_memory_write`` metadata.  It is a factory,
    not a pre-built dict, so the build runs INSIDE the handler's bridge
    ``try/except`` — after the store write and only when the bridge actually
    fires — byte-identical to the pre-migration branches that built the metadata
    as an argument to ``on_memory_write`` (a raising builder was swallowed and
    never blocked the store write).
    """

    store: Any
    manager: Any
    metadata_factory: Any


_MEMORY_TOOL_COMPANION = DispatchCompanion("active_builtin_memory")


def bind_active_memory_tool(store, manager, metadata_factory):
    """Expose the memory store / manager / bridge metadata factory for one dispatch."""
    return _MEMORY_TOOL_COMPANION.bound(
        _MemoryToolBinding(store, manager, metadata_factory)
    )


def _registered_memory_tool_handler(args, **_kwargs) -> str:
    """Register-time handler: sources the store from the companion and fires the
    provider bridge INSIDE the shadow boundary.

    The companion is resolved eagerly here and never stored for a lazy read.
    ``**_kwargs`` (the JSON handler-kwargs snapshot) is ignored for process
    state so a ``MemoryStore`` / ``MemoryManager`` smuggled through dispatch
    kwargs (the old ``kw.get("store")`` seam) can never reach the memory files.

    Argument forwarding matches the pre-migration direct branch exactly
    (``action`` has no default, so a missing action yields the same
    ``memory_tool`` "Unknown action 'None'" error the direct branch produced).
    With no binding (legacy / plugin / hallucinated dispatch) the store is
    ``None`` and ``memory_tool`` returns "Memory is not available" before the
    action is even inspected — byte-identical to the old registration lambda.

    The ``on_memory_write`` bridge fires only for add/replace when a manager is
    bound (truthiness, matching the branches' ``if agent._memory_manager and``
    gate), after the store write, swallowing exceptions raised by either the
    metadata build or the provider — so it never runs on a blocked / stale /
    denied dispatch (whose handler never starts) and never fails the tool.
    """
    args = args if isinstance(args, dict) else {}
    binding = _MEMORY_TOOL_COMPANION.get()
    store = binding.store if binding is not None else None
    result = memory_tool(
        action=args.get("action"),
        target=args.get("target", "memory"),
        content=args.get("content"),
        old_text=args.get("old_text"),
        store=store,
    )
    if (
        binding is not None
        and binding.manager
        and args.get("action") in ("add", "replace")
    ):
        try:
            metadata = (
                binding.metadata_factory()
                if binding.metadata_factory is not None
                else None
            )
            binding.manager.on_memory_write(
                args.get("action", ""),
                args.get("target", "memory"),
                args.get("content", ""),
                metadata=metadata,
            )
        except Exception:
            pass
    return result


def dispatch_builtin_memory_via_registry(
    function_args,
    *,
    store,
    manager=None,
    metadata_factory=None,
    task_id=None,
    session_id=None,
    tool_call_id=None,
    return_outcome=False,
):
    """Route one built-in ``memory`` invocation through the atomic boundary.

    Every agent special-case branch calls this instead of ``memory_tool``
    directly, so the call is captured with the same frozen identity,
    args-digest, and policy context as ordinary registry tools.  The store /
    manager / bridge metadata factory are bound only for the duration of this
    dispatch and only the registered handler can consume them.  ``memory`` is
    statically registered at import, so there is no direct fallback: the entry
    always exists and the adapter's own legacy fallback preserves off-agent
    behavior.  ``metadata_factory`` is a zero-arg callable that is invoked INSIDE
    the handler's swallow-exceptions bridge block (only for add/replace, after
    the store write), so a raising metadata build can never lose or block the
    memory write — byte-identical to the pre-migration inline branches.
    ``return_outcome=True`` returns the adapter's :class:`ToolDispatchOutcome`
    (truthful physical-start proof for the exact-Beta loops); the default
    returns the raw result byte-identically.
    """
    from model_tools import dispatch_agent_owned_registry_tool

    return dispatch_agent_owned_registry_tool(
        "memory",
        function_args if isinstance(function_args, dict) else {},
        task_id=task_id,
        session_id=session_id,
        tool_call_id=tool_call_id,
        companions=(bind_active_memory_tool(store, manager, metadata_factory),),
        return_outcome=return_outcome,
    )


registry.register(
    name="memory",
    toolset="memory",
    schema=MEMORY_SCHEMA,
    handler=_registered_memory_tool_handler,
    check_fn=check_memory_requirements,
    emoji="🧠",
)




