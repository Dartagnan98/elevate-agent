"""Dangerous command approval -- detection, prompting, and per-session state.

This module is the single source of truth for the dangerous command system:
- Pattern detection (DANGEROUS_PATTERNS, detect_dangerous_command)
- Per-session approval state (thread-safe, keyed by session_key)
- Approval prompting (CLI interactive + gateway async)
- Smart approval via auxiliary LLM (auto-approve low-risk commands)
- Permanent allowlist persistence (config.yaml)
"""

import contextvars
import logging
import os
import re
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Optional
from elevate_cli.config import cfg_get

from utils import env_var_enabled, is_truthy_value

logger = logging.getLogger(__name__)


def _beta_approval_policy_active() -> bool:
    """Return whether the exact Realtor Beta safety profile is active.

    Keep this import lazy because ``tools.approval`` is imported during early
    CLI and gateway startup.  The environment fallback preserves the
    fail-closed decision if the policy module cannot be imported from a
    partially installed Beta bundle.
    """
    try:
        from elevate_cli.beta_provider_policy import beta_provider_policy_active

        return beta_provider_policy_active()
    except Exception:
        return os.getenv("ELEVATE_RELEASE_CHANNEL") == "beta"

# Per-thread/per-task gateway session identity.
# Gateway runs agent turns concurrently in executor threads, so reading a
# process-global env var for session identity is racy. Keep env fallback for
# legacy single-threaded callers, but prefer the context-local value when set.
_approval_session_key: contextvars.ContextVar[str] = contextvars.ContextVar(
    "approval_session_key",
    default="",
)


def _fire_approval_hook(hook_name: str, **kwargs) -> None:
    """Invoke a plugin lifecycle hook for the approval system.

    Lazy-imports the plugin manager to avoid circular imports (approval.py is
    imported very early, long before plugins are discovered). Never raises --
    plugin errors are logged and swallowed.

    Only fires for the two approval-specific hooks in VALID_HOOKS:
    pre_approval_request, post_approval_response.
    """
    try:
        from elevate_cli.plugins import invoke_hook
    except Exception:
        # Plugin system not available in this execution context
        # (e.g. bare tool-only imports, minimal test environments).
        return
    try:
        invoke_hook(hook_name, **kwargs)
    except Exception as exc:
        # invoke_hook() already swallows per-callback errors, so reaching here
        # means the dispatch layer itself failed. Log and move on -- approval
        # flow is safety-critical, plugin observability is not.
        logger.debug("Approval hook %s dispatch failed: %s", hook_name, exc)



def set_current_session_key(session_key: str) -> contextvars.Token[str]:
    """Bind the active approval session key to the current context."""
    return _approval_session_key.set(session_key or "")


def reset_current_session_key(token: contextvars.Token[str]) -> None:
    """Restore the prior approval session key context."""
    _approval_session_key.reset(token)


def get_current_session_key(default: str = "default") -> str:
    """Return the active session key, preferring context-local state.

    Resolution order:
    1. approval-specific contextvars (set by gateway before agent.run)
    2. session_context contextvars (set by _set_session_env)
    3. os.environ fallback (CLI, cron, tests)
    """
    session_key = _approval_session_key.get()
    if session_key:
        return session_key
    from gateway.session_context import get_session_env
    return get_session_env("ELEVATE_SESSION_KEY", default)


def _get_session_platform() -> str:
    """Return the current gateway platform from contextvars/env fallback."""
    try:
        from gateway.session_context import get_session_env

        return get_session_env("ELEVATE_SESSION_PLATFORM", "") or ""
    except Exception:
        return os.getenv("ELEVATE_SESSION_PLATFORM", "") or ""


def _is_gateway_approval_context() -> bool:
    """True when this call is inside a gateway/API session.

    Legacy gateway integrations set ELEVATE_GATEWAY_SESSION in process env.
    Newer concurrent gateway paths bind ELEVATE_SESSION_PLATFORM via
    contextvars so approval mode does not depend on process-global flags.

    Cron jobs are NEVER gateway-approval contexts even when they originate
    from a gateway platform (cron binds ELEVATE_SESSION_PLATFORM via
    contextvars for delivery routing). Cron approvals are governed by
    ``approvals.cron_mode`` config, not interactive resolve — letting cron
    fall through to the gateway branch would submit a pending approval
    with no listener and block the job indefinitely.
    """
    if env_var_enabled("ELEVATE_CRON_SESSION"):
        return False
    if env_var_enabled("ELEVATE_GATEWAY_SESSION"):
        return True
    return bool(_get_session_platform())

# Sensitive write targets that should trigger approval even when referenced
# via shell expansions like $HOME or $ELEVATE_HOME.
_SSH_SENSITIVE_PATH = r'(?:~|\$home|\$\{home\})/\.ssh(?:/|$)'
_ELEVATE_ENV_PATH = (
    r'(?:~\/\.hermes/|'
    r'(?:\$home|\$\{home\})/\.hermes/|'
    r'(?:\$hermes_home|\$\{hermes_home\})/)'
    r'\.env\b'
)
_PROJECT_ENV_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*\.env(?:\.[^/\s"\'`]+)*)'
_PROJECT_CONFIG_PATH = r'(?:(?:/|\.{1,2}/)?(?:[^\s/"\'`]+/)*config\.yaml)'
_SHELL_RC_FILES = (
    r'(?:~|\$home|\$\{home\})/\.'
    r'(?:bashrc|zshrc|profile|bash_profile|zprofile)\b'
)
_CREDENTIAL_FILES = (
    r'(?:~|\$home|\$\{home\})/\.'
    r'(?:netrc|pgpass|npmrc|pypirc)\b'
)
# macOS: /etc, /var, /tmp, /home are symlinks to /private/{etc,var,tmp,home}.
# A command written to target /private/etc/sudoers works identically to
# /etc/sudoers on macOS but bypasses a plain "/etc/" pattern check. Match
# both forms. Inspired by Claude Code 2.1.113's "dangerous path protection".
_MACOS_PRIVATE_SYSTEM_PATH = r'/private/(?:etc|var|tmp|home)/'
# System-config paths that should trigger approval for any write/edit,
# collapsing /etc, its macOS /private/etc mirror, and /etc/sudoers.d/ into
# one shared fragment so new DANGEROUS_PATTERNS stay consistent.
_SYSTEM_CONFIG_PATH = (
    rf'(?:/etc/|{_MACOS_PRIVATE_SYSTEM_PATH})'
)
_SENSITIVE_WRITE_TARGET = (
    rf'(?:{_SYSTEM_CONFIG_PATH}|/dev/sd|'
    rf'{_SSH_SENSITIVE_PATH}|'
    rf'{_ELEVATE_ENV_PATH}|'
    rf'{_SHELL_RC_FILES}|'
    rf'{_CREDENTIAL_FILES})'
)
_PROJECT_SENSITIVE_WRITE_TARGET = rf'(?:{_PROJECT_ENV_PATH}|{_PROJECT_CONFIG_PATH})'
_COMMAND_TAIL = r'(?:\s*(?:&&|\|\||;).*)?$'

# =========================================================================
# Hardline (unconditional) blocklist
# =========================================================================
#
# Commands so catastrophic they should NEVER run via the agent, regardless
# of --yolo, /yolo, approvals.mode=off, or cron approve mode.  This is a
# floor below yolo: opting into yolo is the user trusting the agent with
# their files and services, not trusting it to wipe the disk or power the
# box off.
#
# Hardline only applies to environments that can actually damage the host
# (local, ssh, container-host cron).  Containerized backends (docker,
# singularity, modal, daytona) already bypass the dangerous-command layer
# because nothing they do can touch the host, so we leave that behavior
# alone.
#
# The list is deliberately tiny — only things with no recovery path:
# filesystem destruction rooted at /, raw block device overwrites, kernel
# shutdown/reboot, and denial-of-service commands that take the host down.
# Recoverable-but-costly operations (git reset --hard, rm -rf /tmp/x,
# chmod -R 777, curl|sh) stay in DANGEROUS_PATTERNS where yolo can pass
# them through — that's what yolo is for.
#
# Inspired by Mercury Agent's permission-hardened blocklist
# (https://github.com/cosmicstack-labs/mercury-agent).

# Regex fragment matching the *start* of a command (i.e. positions where
# a shell would begin parsing a new command).  Used by shutdown/reboot
# patterns so they don't fire on "echo reboot" or "grep 'shutdown' log".
# Matches: start of string, after command separators (; && || | newline),
# after subshell openers ( `$(` or backtick ), optionally consuming
# leading wrapper commands (sudo, env VAR=VAL, exec, nohup, setsid).
_CMDPOS = (
    r'(?:^|[;&|\n`]|\$\()'         # start position
    r'\s*'                          # optional whitespace
    r'(?:sudo\s+(?:-[^\s]+\s+)*)?'  # optional sudo with flags
    r'(?:env\s+(?:\w+=\S*\s+)*)?'   # optional env with VAR=VAL pairs
    r'(?:(?:exec|nohup|setsid|time)\s+)*'  # optional wrapper commands
    r'\s*'
)

HARDLINE_PATTERNS = [
    # rm recursive targeting the root filesystem or protected roots
    (r'\brm\s+(-[^\s]*\s+)*(/|/\*|/ \*)(\s|$)', "recursive delete of root filesystem"),
    (r'\brm\s+(-[^\s]*\s+)*(/home|/home/\*|/root|/root/\*|/etc|/etc/\*|/usr|/usr/\*|/var|/var/\*|/bin|/bin/\*|/sbin|/sbin/\*|/boot|/boot/\*|/lib|/lib/\*)(\s|$)', "recursive delete of system directory"),
    (r'\brm\s+(-[^\s]*\s+)*(~|\$HOME)(/?|/\*)?(\s|$)', "recursive delete of home directory"),
    # Filesystem format
    (r'\bmkfs(\.[a-z0-9]+)?\b', "format filesystem (mkfs)"),
    # Raw block device overwrites (dd + redirection)
    (r'\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*', "dd to raw block device"),
    (r'>\s*/dev/(sd|nvme|hd|mmcblk|vd|xvd)[a-z0-9]*\b', "redirect to raw block device"),
    # Fork bomb (classic shell form)
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),
    # Kill every process on the system
    (r'\bkill\s+(-[^\s]+\s+)*-1\b', "kill all processes"),
    # System shutdown / reboot — anchor to command position (start of line,
    # after a command separator, or after sudo/env wrappers) so we don't
    # false-positive on "echo reboot" or "grep 'shutdown' logs".
    # _CMDPOS matches start-of-command positions.
    (_CMDPOS + r'(shutdown|reboot|halt|poweroff)\b', "system shutdown/reboot"),
    (_CMDPOS + r'init\s+[06]\b', "init 0/6 (shutdown/reboot)"),
    (_CMDPOS + r'systemctl\s+(poweroff|reboot|halt|kexec)\b', "systemctl poweroff/reboot"),
    (_CMDPOS + r'telinit\s+[06]\b', "telinit 0/6 (shutdown/reboot)"),
]

# Pre-compiled variant used by the hot-path matcher. Building these at module
# load eliminates the ~2.6 ms cold-cache re.compile fan-out on the first
# terminal() call per process (12 HARDLINE + 47 DANGEROUS patterns, each
# potentially evicted from Python's 512-entry ``re._cache`` by unrelated
# regex work elsewhere in the agent). DANGEROUS_PATTERNS_COMPILED is built
# at the end of this module after DANGEROUS_PATTERNS is defined.
_RE_FLAGS = re.IGNORECASE | re.DOTALL
HARDLINE_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in HARDLINE_PATTERNS
]


# =========================================================================
# Sudo stdin guard — block password guessing via "sudo -S"
# =========================================================================
# When SUDO_PASSWORD is not configured, any explicit "sudo -S" in the
# command is the LLM piping a guessed password via stdin.  This is a
# brute-force attack vector: the model iterates through candidate
# passwords, inspects sudo's "Sorry, try again" output, and refines.
# Treat this as an unconditional block — there is never a legitimate
# reason for the agent to pipe passwords to sudo -S when no password
# has been configured.
_SUDO_STDIN_RE = re.compile(
    r'(?:^|[;&|`\n]|&&|\|\||\$\()\s*sudo\s+-S\b',
    re.IGNORECASE)


def _check_sudo_stdin_guard(command: str) -> tuple:
    """Detect ``sudo -S`` (stdin password) without configured SUDO_PASSWORD.

    When SUDO_PASSWORD is set, ``_transform_sudo_command`` injects ``-S``
    internally — that path is legitimate and handled elsewhere.  This guard
    only fires when SUDO_PASSWORD is *not* set, meaning the LLM explicitly
    wrote ``sudo -S`` to pipe a guessed password.

    Returns:
        (is_blocked: bool, description: str | None)
    """
    if "SUDO_PASSWORD" in os.environ:
        return (False, None)
    normalized = _normalize_command_for_detection(command).lower()
    if _SUDO_STDIN_RE.search(normalized):
        return (True, "sudo password guessing via stdin (sudo -S)")
    return (False, None)


def detect_hardline_command(command: str) -> tuple:
    """Check if a command matches the unconditional hardline blocklist.

    Returns:
        (is_hardline, description) or (False, None)
    """
    normalized = _normalize_command_for_detection(command).lower()
    for pattern_re, description in HARDLINE_PATTERNS_COMPILED:
        if pattern_re.search(normalized):
            return (True, description)
    return (False, None)


def _hardline_block_result(description: str) -> dict:
    """Build the standard block result for a hardline match."""
    return {
        "approved": False,
        "hardline": True,
        "message": (
            f"BLOCKED (hardline): {description}. "
            "This command is on the unconditional blocklist and cannot "
            "be executed via the agent — not even with --yolo, /yolo, "
            "approvals.mode=off, or cron approve mode. If you genuinely "
            "need to run it, run it yourself in a terminal outside the "
            "agent."
        ),
    }


def _sudo_stdin_block_result(description: str) -> dict:
    """Build the standard block result for sudo stdin guard."""
    return {
        "approved": False,
        "message": (
            f"BLOCKED: {description}. "
            "Do not pipe passwords to 'sudo -S' — this is a brute-force "
            "attack vector. Set SUDO_PASSWORD in your .env file if the "
            "agent needs passwordless sudo, or run the sudo command "
            "manually in your own terminal."
        ),
    }


# =========================================================================
# Dangerous command patterns
# =========================================================================

DANGEROUS_PATTERNS = [
    (r'\brm\s+(-[^\s]*\s+)*/', "delete in root path"),
    (r'\brm\s+-[^\s]*r', "recursive delete"),
    (r'\brm\s+--recursive\b', "recursive delete (long flag)"),
    (r'\bchmod\s+(-[^\s]*\s+)*(777|666|o\+[rwx]*w|a\+[rwx]*w)\b', "world/other-writable permissions"),
    (r'\bchmod\s+--recursive\b.*(777|666|o\+[rwx]*w|a\+[rwx]*w)', "recursive world/other-writable (long flag)"),
    (r'\bchown\s+(-[^\s]*)?R\s+root', "recursive chown to root"),
    (r'\bchown\s+--recursive\b.*root', "recursive chown to root (long flag)"),
    (r'\bmkfs\b', "format filesystem"),
    (r'\bdd\s+.*if=', "disk copy"),
    (r'>\s*/dev/sd', "write to block device"),
    (r'\bDROP\s+(TABLE|DATABASE)\b', "SQL DROP"),
    # Use [^\n]* instead of .* so DOTALL mode does not cause a WHERE clause on the
    # *next* line to satisfy the negative lookahead, silently allowing DELETE without WHERE.
    (r'\bDELETE\s+FROM\b(?![^\n]*\bWHERE\b)', "SQL DELETE without WHERE"),
    (r'\bTRUNCATE\s+(TABLE)?\s*\w', "SQL TRUNCATE"),
    (rf'>\s*{_SYSTEM_CONFIG_PATH}', "overwrite system config"),
    (r'\bsystemctl\s+(-[^\s]+\s+)*(stop|restart|disable|mask)\b', "stop/restart system service"),
    (r'\bkill\s+-9\s+-1\b', "kill all processes"),
    (r'\bpkill\s+-9\b', "force kill processes"),
    # killall with SIGKILL (parallel to pkill -9). Catches -9 / -KILL /
    # -s KILL / -SIGKILL forms, and also `killall -r <regex>` broad sweeps
    # that can wipe out unrelated processes by accident.
    # Inspired by Claude Code 2.1.113 expanded deny rules.
    (r'\bkillall\s+(-[^\s]*\s+)*-(9|KILL|SIGKILL)\b', "force kill processes (killall -KILL)"),
    (r'\bkillall\s+(-[^\s]*\s+)*-s\s+(KILL|SIGKILL|9)\b', "force kill processes (killall -s KILL)"),
    (r'\bkillall\s+(-[^\s]*\s+)*-r\b', "kill processes by regex (killall -r)"),
    (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:', "fork bomb"),
    # Any shell invocation via -c or combined flags like -lc, -ic, etc.
    (r'\b(bash|sh|zsh|ksh)\s+-[^\s]*c(\s+|$)', "shell command via -c/-lc flag"),
    (r'\b(python[23]?|perl|ruby|node)\s+-[ec]\s+', "script execution via -e/-c flag"),
    (r'\b(curl|wget)\b.*\|\s*(ba)?sh\b', "pipe remote content to shell"),
    (r'\b(bash|sh|zsh|ksh)\s+<\s*<?\s*\(\s*(curl|wget)\b', "execute remote script via process substitution"),
    (rf'\btee\b.*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via tee"),
    (rf'>>?\s*["\']?{_SENSITIVE_WRITE_TARGET}', "overwrite system file via redirection"),
    (rf'\btee\b.*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "overwrite project env/config via tee"),
    (rf'>>?\s*["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "overwrite project env/config via redirection"),
    (r'\bxargs\s+.*\brm\b', "xargs with rm"),
    # find -exec rm / -execdir rm — the -execdir variant (same semantics,
    # runs in the directory of each match) was previously missed. Claude
    # Code 2.1.113 tightened their equivalent find rule to stop auto-
    # approving -exec / -delete flags.
    (r'\bfind\b.*-exec(?:dir)?\s+(/\S*/)?rm\b', "find -exec/-execdir rm"),
    (r'\bfind\b.*-delete\b', "find -delete"),
    # Gateway lifecycle protection: prevent the agent from killing its own
    # gateway process.  These commands trigger a gateway restart/stop that
    # terminates all running agents mid-work.
    (r'\bhermes\s+gateway\s+(stop|restart)\b', "stop/restart hermes gateway (kills running agents)"),
    (r'\bhermes\s+update\b', "hermes update (restarts gateway, kills running agents)"),
    # Gateway protection: never start gateway outside systemd management
    (r'gateway\s+run\b.*(&\s*$|&\s*;|\bdisown\b|\bsetsid\b)', "start gateway outside systemd (use 'systemctl --user restart hermes-gateway')"),
    (r'\bnohup\b.*gateway\s+run\b', "start gateway outside systemd (use 'systemctl --user restart hermes-gateway')"),
    # Self-termination protection: prevent agent from killing its own process
    (r'\b(pkill|killall)\b.*\b(hermes|gateway|cli\.py)\b', "kill hermes/gateway process (self-termination)"),
    # Self-termination via kill + command substitution (pgrep/pidof).
    # The name-based pattern above catches `pkill hermes` but not
    # `kill -9 $(pgrep -f hermes)` because the substitution is opaque
    # to regex at detection time. Catch the structural pattern instead.
    (r'\bkill\b.*\$\(\s*pgrep\b', "kill process via pgrep expansion (self-termination)"),
    (r'\bkill\b.*`\s*pgrep\b', "kill process via backtick pgrep expansion (self-termination)"),
    # File copy/move/edit into sensitive system paths (/etc/ and macOS
    # /private/etc/ mirror).
    (rf'\b(cp|mv|install)\b.*\s{_SYSTEM_CONFIG_PATH}', "copy/move file into system config path"),
    (rf'\b(cp|mv|install)\b.*\s["\']?{_PROJECT_SENSITIVE_WRITE_TARGET}["\']?{_COMMAND_TAIL}', "overwrite project env/config file"),
    (rf'\bsed\s+-[^\s]*i.*\s{_SYSTEM_CONFIG_PATH}', "in-place edit of system config"),
    (rf'\bsed\s+--in-place\b.*\s{_SYSTEM_CONFIG_PATH}', "in-place edit of system config (long flag)"),
    # Script execution via heredoc — bypasses the -e/-c flag patterns above.
    # `python3 << 'EOF'` feeds arbitrary code via stdin without -c/-e flags.
    (r'\b(python[23]?|perl|ruby|node)\s+<<', "script execution via heredoc"),
    # Git destructive operations that can lose uncommitted work or rewrite
    # shared history. Not captured by rm/chmod/etc patterns.
    (r'\bgit\s+reset\s+--hard\b', "git reset --hard (destroys uncommitted changes)"),
    (r'\bgit\s+push\b.*--force\b', "git force push (rewrites remote history)"),
    (r'\bgit\s+push\b.*-f\b', "git force push short flag (rewrites remote history)"),
    (r'\bgit\s+clean\s+-[^\s]*f', "git clean with force (deletes untracked files)"),
    (r'\bgit\s+branch\s+-D\b', "git branch force delete"),
    # Script execution after chmod +x — catches the two-step pattern where
    # a script is first made executable then immediately run. The script
    # content may contain dangerous commands that individual patterns miss.
    (r'\bchmod\s+\+x\b.*[;&|]+\s*\./', "chmod +x followed by immediate execution"),
    # Sudo with stdin / askpass / shell / list-privs flags. An LLM-driven
    # agent has no TTY, so sudo invocations that succeed without human
    # interaction are those reading the password from stdin (-S/--stdin)
    # or via an askpass helper (-A/--askpass). The shell-launch (-s) and
    # list-privileges (-a) flags are also gated since they are
    # privilege-relevant invocations the agent can chain after acquiring
    # the password (e.g. read SUDO_PASSWORD from .env -> sudo -S -s ->
    # root shell). Plain `sudo cmd` (no flag) is TTY-bound and excluded.
    # `_normalize_command_for_detection` lowercases input before pattern
    # matching, so case variants of S/s and A/a collapse — both forms
    # are gated below. Lazy `[^;|&\n]*?` allows flag arguments (e.g.
    # `sudo -u root -S whoami`) without spanning command separators. See
    # #17873 category 4.
    (r'\bsudo\b[^;|&\n]*?\s+(?:-s\b|--stdin\b|-a\b|--askpass\b)',
     "sudo with privilege flag (stdin/askpass/shell/list)"),
    # Combined short-flag form: -nS, -ns, -sa, -las — sudo flags packed
    # into a single -X token. Catches the same threat class.
    (r'\bsudo\b[^;|&\n]*?\s+-[a-z]*[sa][a-z]*\b',
     "sudo with combined-flag privilege escalation"),
]


# Pre-compiled variant (same rationale as HARDLINE_PATTERNS_COMPILED above).
DANGEROUS_PATTERNS_COMPILED = [
    (re.compile(pattern, _RE_FLAGS), description)
    for pattern, description in DANGEROUS_PATTERNS
]


def _legacy_pattern_key(pattern: str) -> str:
    """Reproduce the old regex-derived approval key for backwards compatibility."""
    return pattern.split(r'\b')[1] if r'\b' in pattern else pattern[:20]


_PATTERN_KEY_ALIASES: dict[str, set[str]] = {}
for _pattern, _description in DANGEROUS_PATTERNS:
    _legacy_key = _legacy_pattern_key(_pattern)
    _canonical_key = _description
    _PATTERN_KEY_ALIASES.setdefault(_canonical_key, set()).update({_canonical_key, _legacy_key})
    _PATTERN_KEY_ALIASES.setdefault(_legacy_key, set()).update({_legacy_key, _canonical_key})


def _approval_key_aliases(pattern_key: str) -> set[str]:
    """Return all approval keys that should match this pattern.

    New approvals use the human-readable description string, but older
    command_allowlist entries and session approvals may still contain the
    historical regex-derived key.
    """
    return _PATTERN_KEY_ALIASES.get(pattern_key, {pattern_key})


# =========================================================================
# Detection
# =========================================================================

def _normalize_command_for_detection(command: str) -> str:
    """Normalize a command string before dangerous-pattern matching.

    Strips ANSI escape sequences (full ECMA-48 via tools.ansi_strip),
    null bytes, and normalizes Unicode fullwidth characters so that
    obfuscation techniques cannot bypass the pattern-based detection.
    """
    from tools.ansi_strip import strip_ansi

    # Strip all ANSI escape sequences (CSI, OSC, DCS, 8-bit C1, etc.)
    command = strip_ansi(command)
    # Strip null bytes
    command = command.replace('\x00', '')
    # Normalize Unicode (fullwidth Latin, halfwidth Katakana, etc.)
    command = unicodedata.normalize('NFKC', command)
    return command


def detect_dangerous_command(command: str) -> tuple:
    """Check if a command matches any dangerous patterns.

    Returns:
        (is_dangerous, pattern_key, description) or (False, None, None)
    """
    command_lower = _normalize_command_for_detection(command).lower()
    for pattern_re, description in DANGEROUS_PATTERNS_COMPILED:
        if pattern_re.search(command_lower):
            pattern_key = description
            return (True, pattern_key, description)
    return (False, None, None)


# =========================================================================
# Per-session approval state (thread-safe)
# =========================================================================

_lock = threading.Lock()
_pending: dict[str, dict] = {}
_session_approved: dict[str, set] = {}
_session_yolo: set[str] = set()
_permanent_approved: set = set()

# =========================================================================
# Blocking gateway approval (mirrors CLI's synchronous input() flow)
# =========================================================================
# Per-session QUEUE of pending approvals.  Multiple threads (parallel
# subagents, execute_code RPC handlers) can block concurrently — each gets
# its own threading.Event.  /approve resolves the oldest, /approve all
# resolves every pending approval in the session.


class _ApprovalEntry:
    """One pending dangerous-command approval inside a gateway session."""
    __slots__ = (
        "correlation_id",
        "data",
        "event",
        "receipt_lock",
        "receipt_outcome",
        "receipt_retry_scheduled",
        "request_id",
        "resolution_reason",
        "result",
    )

    def __init__(self, data: dict):
        # Never derive this identifier from a command, session, platform, or
        # caller-provided value.  It crosses the UI boundary, so it must be an
        # opaque capability identifying exactly one pending decision.
        self.request_id = uuid.uuid4().hex
        self.event = threading.Event()
        self.data = dict(data)    # command, description, pattern_keys, …
        self.data["request_id"] = self.request_id
        self.data["requestId"] = self.request_id
        self.correlation_id = _opaque_approval_lineage_id(
            self.data.get("correlation_id") or _current_approval_correlation_id()
        )
        self.data.pop("correlation_id", None)
        if self.correlation_id:
            self.data["correlation_id"] = self.correlation_id
        # Session/message/request identifiers are intentionally not receipt
        # lineage.  Only the central correlation layer may mint a joinable
        # ``corr_``/``attempt_`` value.
        self.data.pop("session_id", None)
        self.result: Optional[str] = None  # "once"|"session"|"always"|"deny"
        self.resolution_reason = ""
        self.receipt_lock = threading.Lock()
        self.receipt_outcome: Optional[str] = None
        self.receipt_retry_scheduled = False


_gateway_queues: dict[str, list] = {}        # session_key → [_ApprovalEntry, …]
_gateway_notify_cbs: dict[str, object] = {}  # session_key → callable(approval_data)

_VALID_GATEWAY_APPROVAL_CHOICES = frozenset({"once", "session", "always", "deny"})
_OPAQUE_APPROVAL_LINEAGE_RE = re.compile(r"^(?:corr_|attempt_)[0-9a-f]{32}$")


def _opaque_approval_lineage_id(value: object) -> str:
    """Keep canonical random lineage only; never persist semantic wire IDs."""
    candidate = str(value or "").strip()
    return candidate if _OPAQUE_APPROVAL_LINEAGE_RE.fullmatch(candidate) else ""


def _current_approval_correlation_id() -> str:
    """Return central canonical lineage when the gateway bound one."""
    try:
        from gateway.session_context import get_session_env

        return get_session_env("ELEVATE_SESSION_CORRELATION_ID", "") or ""
    except Exception:
        return os.getenv("ELEVATE_SESSION_CORRELATION_ID", "") or ""


def _record_approval_event(
    event_type: str,
    entry: _ApprovalEntry,
    _session_key: str,
    *,
    outcome: str,
    reason: str,
) -> bool:
    """Append a content-free approval audit event to the local recorder."""
    try:
        from elevate_cli.diagnostics.session_recorder import record_session_event

        return bool(
            record_session_event(
                event_type,
                # Never write a raw gateway session/chat/user key. Opaque
                # correlation + request IDs are enough to join the receipt.
                session_id=None,
                correlation_id=entry.correlation_id or None,
                payload={
                    "request_id": entry.request_id,
                    "outcome": outcome,
                    "reason": reason,
                    "status": "pending" if event_type == "approval.requested" else "resolved",
                },
                severity="warning" if outcome in {"deny", "timeout"} else "info",
                source="approval",
                component="tools.approval",
            )
        )
    except Exception:
        logger.debug("approval receipt write failed", exc_info=True)
        return False


def _record_approval_receipt(
    entry: _ApprovalEntry,
    session_key: str,
    *,
    outcome: str,
    reason: str,
) -> None:
    """Record one durable terminal receipt for a pending approval entry."""
    # Serialize the claim and write per entry.  The prior claim-write-reset
    # sequence released its lock during I/O: a waiter could see the provisional
    # claim, skip its retry, and then the failed writer reset it to ``None`` —
    # permanently losing the receipt.  A per-entry lock makes success
    # exactly-once and failed writes retryable without blocking queue traffic.
    with entry.receipt_lock:
        if entry.receipt_outcome is not None or entry.receipt_retry_scheduled:
            return
        if _record_approval_event(
            "approval.decision",
            entry,
            session_key,
            outcome=outcome,
            reason=reason,
        ):
            entry.receipt_outcome = outcome
            return

        # A recorder can be temporarily unavailable while a session file is
        # rotating. Retry once off the approval's critical return path: the
        # command decision must not sit behind another disk attempt, and a
        # daemon retry remains single-flight under ``receipt_lock``.
        entry.receipt_retry_scheduled = True

    def _retry() -> None:
        with entry.receipt_lock:
            try:
                if entry.receipt_outcome is not None:
                    return
                if _record_approval_event(
                    "approval.decision",
                    entry,
                    session_key,
                    outcome=outcome,
                    reason=reason,
                ):
                    entry.receipt_outcome = outcome
            finally:
                entry.receipt_retry_scheduled = False

    threading.Thread(
        target=_retry,
        name=f"approval-receipt-{entry.request_id[:8]}",
        daemon=True,
    ).start()


def register_gateway_notify(session_key: str, cb) -> None:
    """Register a per-session callback for sending approval requests to the user.

    The callback signature is ``cb(approval_data: dict) -> None`` where
    *approval_data* contains ``command``, ``description``, and
    ``pattern_keys``.  The callback bridges sync→async (runs in the agent
    thread, must schedule the actual send on the event loop).
    """
    with _lock:
        _gateway_notify_cbs[session_key] = cb


def unregister_gateway_notify(session_key: str) -> None:
    """Unregister the per-session gateway approval callback.

    Signals ALL blocked threads for this session so they don't hang forever
    (e.g. when the agent run finishes or is interrupted).
    """
    with _lock:
        _gateway_notify_cbs.pop(session_key, None)
        entries = _gateway_queues.pop(session_key, [])
        # Queue removal, terminal result, and waiter publication are one
        # state transition.  A timeout cannot interleave and misreport these
        # cleanup denials as timeouts.
        for entry in entries:
            entry.result = "deny"
            entry.resolution_reason = "gateway_unregistered"
            entry.event.set()
    for entry in entries:
        _record_approval_receipt(
            entry,
            session_key,
            outcome="deny",
            reason=entry.resolution_reason,
        )


def resolve_gateway_approval(
    session_key: str,
    choice: str,
    resolve_all: bool = False,
    *,
    request_id: str | None = None,
    reason: str = "user_response",
) -> int:
    """Called by the gateway's /approve or /deny handler to unblock
    waiting agent thread(s).

    When *request_id* is provided, only that exact pending entry may be
    resolved.  Unknown or stale IDs return zero and leave the whole queue
    untouched.  The ID-targeted path is used by the in-app/TUI UI.

    The FIFO and *resolve_all* paths remain only for compatibility with the
    existing Stable text commands (``/approve``, ``/deny``, and their ``all``
    variants), whose message protocols do not yet return an approval ID.

    Returns the number of approvals resolved (0 means nothing was pending).
    """
    normalized_choice = str(choice or "").strip().lower()
    if normalized_choice not in _VALID_GATEWAY_APPROVAL_CHOICES:
        return 0
    target_id = str(request_id or "").strip()

    with _lock:
        queue = _gateway_queues.get(session_key)
        if not queue:
            return 0
        if target_id:
            target = next(
                (entry for entry in queue if entry.request_id == target_id),
                None,
            )
            if target is None:
                return 0
            targets = [target]
            queue.remove(target)
        elif resolve_all:
            targets = list(queue)
            queue.clear()
        else:
            targets = [queue.pop(0)]
        if not queue:
            _gateway_queues.pop(session_key, None)
        # Publish result + event atomically with queue removal.  Otherwise a
        # waiter at its timeout boundary can observe "not queued" but still
        # see a missing result and record a false timeout.
        for entry in targets:
            entry.result = normalized_choice
            entry.resolution_reason = reason
            entry.event.set()

    for entry in targets:
        _record_approval_receipt(
            entry,
            session_key,
            outcome=normalized_choice,
            reason=reason,
        )
    return len(targets)


def has_blocking_approval(session_key: str) -> bool:
    """Check if a session has one or more blocking gateway approvals waiting."""
    with _lock:
        return bool(_gateway_queues.get(session_key))


def submit_pending(session_key: str, approval: dict):
    """Store a pending approval request for a session."""
    with _lock:
        _pending[session_key] = approval


def approve_session(session_key: str, pattern_key: str):
    """Approve a pattern for this session only."""
    with _lock:
        _session_approved.setdefault(session_key, set()).add(pattern_key)


def enable_session_yolo(session_key: str) -> None:
    """Enable YOLO bypass for a single session key."""
    if not session_key or _beta_approval_policy_active():
        return
    with _lock:
        _session_yolo.add(session_key)


def disable_session_yolo(session_key: str) -> None:
    """Disable YOLO bypass for a single session key."""
    if not session_key:
        return
    with _lock:
        _session_yolo.discard(session_key)


def clear_session(session_key: str) -> None:
    """Remove all approval and yolo state for a given session."""
    if not session_key:
        return
    with _lock:
        _session_approved.pop(session_key, None)
        _session_yolo.discard(session_key)
        _session_permission_mode.pop(session_key, None)
        _pending.pop(session_key, None)
        entries = _gateway_queues.pop(session_key, [])
        # Session-boundary cleanup should cancel blocked waits immediately,
        # with the result visible before the event wakes any waiter.
        for entry in entries:
            entry.result = "deny"
            entry.resolution_reason = "session_cleared"
            entry.event.set()
    for entry in entries:
        _record_approval_receipt(
            entry,
            session_key,
            outcome="deny",
            reason=entry.resolution_reason,
        )


def is_session_yolo_enabled(session_key: str) -> bool:
    """Return True when YOLO bypass is enabled for a specific session."""
    if not session_key or _beta_approval_policy_active():
        return False
    with _lock:
        return session_key in _session_yolo


def is_current_session_yolo_enabled() -> bool:
    """Return True when the active approval session has YOLO bypass enabled."""
    return is_session_yolo_enabled(get_current_session_key(default=""))


# ---------------------------------------------------------------------------
# Accepted-turn effect policy
# ---------------------------------------------------------------------------
# This vocabulary describes what a tool call can do, independently of the
# tool's name.  It is deliberately small: scopes refine an effect without
# creating a second, incompatible permission language (for example,
# ``write_external:crm`` or ``message_external:sms``).
class EffectKind(str, Enum):
    READ = "read"
    WRITE_LOCAL = "write_local"
    WRITE_EXTERNAL = "write_external"
    MESSAGE_EXTERNAL = "message_external"
    DESTRUCTIVE = "destructive"
    CREDENTIAL_ACCESS = "credential_access"
    FINANCIAL = "financial"
    SPAWN = "spawn"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        return self.value


_EFFECT_SCOPE_RE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,127}$")


@dataclass(frozen=True, slots=True)
class Effect:
    """One frozen effect capability, optionally narrowed to a scope."""

    kind: EffectKind
    scope: Optional[str] = None

    def __post_init__(self) -> None:
        kind = self.kind
        if not isinstance(kind, EffectKind):
            try:
                kind = EffectKind(str(kind).strip().lower())
            except ValueError as exc:
                raise ValueError(f"Unknown effect kind: {self.kind!r}") from exc
            object.__setattr__(self, "kind", kind)

        if self.scope is None:
            return
        scope = str(self.scope).strip().lower()
        if not _EFFECT_SCOPE_RE.fullmatch(scope):
            raise ValueError(f"Invalid effect scope: {self.scope!r}")
        object.__setattr__(self, "scope", scope)

    @classmethod
    def parse(cls, value: "Effect | EffectKind | str") -> "Effect":
        """Parse ``kind`` or ``kind:scope`` into a canonical frozen effect."""
        if isinstance(value, cls):
            return value
        if isinstance(value, EffectKind):
            return cls(value)
        if not isinstance(value, str):
            raise TypeError(
                "Effect must be Effect, EffectKind, or str; "
                f"got {type(value).__name__}"
            )
        raw = value.strip().lower()
        if not raw:
            raise ValueError("Effect value cannot be empty")
        kind, separator, scope = raw.partition(":")
        if separator and not scope:
            raise ValueError(f"Invalid scoped effect: {value!r}")
        return cls(EffectKind(kind), scope if separator else None)

    def __str__(self) -> str:
        if self.scope:
            return f"{self.kind.value}:{self.scope}"
        return self.kind.value


EffectInput = Effect | EffectKind | str


def normalize_effects(
    effects: EffectInput | Iterable[EffectInput] | None,
) -> frozenset[Effect]:
    """Return a canonical immutable effect set.

    ``None`` and an empty iterable remain empty here so policy construction can
    intentionally narrow to zero capabilities.  Registry resolution and
    authorization separately convert an undeclared/empty operation to
    ``unknown`` so restricted execution fails closed.
    """
    if effects is None:
        return frozenset()
    if isinstance(effects, (Effect, EffectKind, str)):
        values: Iterable[EffectInput] = (effects,)
    else:
        values = effects
    return frozenset(Effect.parse(effect) for effect in values)


def _effect_is_within(effect: Effect, capability: Effect) -> bool:
    """Whether *effect* is no broader than *capability*."""
    if effect.kind is not capability.kind:
        return False
    # An unscoped capability covers every scope of the same kind.  A scoped
    # capability never covers an unscoped (broader) request.
    return capability.scope is None or effect.scope == capability.scope


def _effect_intersection(left: Effect, right: Effect) -> Optional[Effect]:
    """Return the narrower common capability, or None when disjoint."""
    if left.kind is not right.kind:
        return None
    if left.scope == right.scope:
        return left
    if left.scope is None:
        return right
    if right.scope is None:
        return left
    return None


class ExecutionPolicyMode(str, Enum):
    DEFAULT = "default"
    PLAN = "plan"
    READ_ONLY = "read_only"
    DRAFT_ONLY = "draft_only"

    @classmethod
    def parse(cls, value: "ExecutionPolicyMode | str") -> "ExecutionPolicyMode":
        if isinstance(value, cls):
            return value
        normalized = str(value).strip().lower().replace("-", "_")
        return cls(normalized)


_ALL_DECLARED_EFFECTS = frozenset(
    Effect(kind) for kind in EffectKind if kind is not EffectKind.UNKNOWN
)
_POLICY_MODE_CEILINGS = MappingProxyType({
    ExecutionPolicyMode.DEFAULT: _ALL_DECLARED_EFFECTS,
    ExecutionPolicyMode.PLAN: frozenset({
        Effect(EffectKind.READ),
        Effect(EffectKind.WRITE_LOCAL, "session_plan"),
    }),
    ExecutionPolicyMode.READ_ONLY: frozenset({Effect(EffectKind.READ)}),
    ExecutionPolicyMode.DRAFT_ONLY: frozenset({
        Effect(EffectKind.READ),
        Effect(EffectKind.WRITE_LOCAL, "draft"),
        Effect(EffectKind.WRITE_LOCAL, "session_plan"),
    }),
})

# Existing Claude-style permission modes are an input vocabulary, not an
# execution policy. Keep the translation total and immutable so a typo or a
# future mode cannot silently inherit the permissive default ceiling.
PERMISSION_MODE_POLICY_MODES = MappingProxyType({
    "default": ExecutionPolicyMode.DEFAULT,
    "acceptEdits": ExecutionPolicyMode.DEFAULT,
    "plan": ExecutionPolicyMode.PLAN,
    "bypassPermissions": ExecutionPolicyMode.DEFAULT,
    "read_only": ExecutionPolicyMode.READ_ONLY,
})
_BETA_PERMISSION_MODE_POLICY_MODES = MappingProxyType({
    "default": ExecutionPolicyMode.READ_ONLY,
    "acceptEdits": ExecutionPolicyMode.DRAFT_ONLY,
    "plan": ExecutionPolicyMode.PLAN,
    "bypassPermissions": ExecutionPolicyMode.DRAFT_ONLY,
    "read_only": ExecutionPolicyMode.READ_ONLY,
})


class PolicyWideningError(ValueError):
    """Raised when a derived accepted-turn policy would add capability."""


@dataclass(frozen=True, slots=True)
class ExecutionPolicy:
    """Immutable capabilities frozen when one user turn is accepted.

    A policy can produce a narrower child policy, but it cannot change the
    accepted-turn identity or add a capability.  Scopes participate in the
    intersection: ``write_local:workspace`` is narrower than ``write_local``.
    """

    accepted_turn_id: str
    mode: ExecutionPolicyMode
    allowed_effects: frozenset[Effect]

    def __post_init__(self) -> None:
        if not isinstance(self.accepted_turn_id, str):
            raise TypeError("accepted_turn_id must be a string")
        accepted_turn_id = self.accepted_turn_id.strip()
        if not accepted_turn_id:
            raise ValueError("accepted_turn_id is required")
        object.__setattr__(self, "accepted_turn_id", accepted_turn_id)

        try:
            mode = ExecutionPolicyMode.parse(self.mode)
        except ValueError as exc:
            raise ValueError(f"Unknown execution policy mode: {self.mode!r}") from exc
        object.__setattr__(self, "mode", mode)

        normalized = normalize_effects(self.allowed_effects)
        if any(effect.kind is EffectKind.UNKNOWN for effect in normalized):
            raise ValueError("unknown cannot be granted by an execution policy")
        ceiling = _POLICY_MODE_CEILINGS[mode]
        outside_ceiling = {
            effect
            for effect in normalized
            if not any(_effect_is_within(effect, limit) for limit in ceiling)
        }
        if outside_ceiling:
            rendered = ", ".join(sorted(map(str, outside_ceiling)))
            raise ValueError(f"Effects exceed {mode.value} policy ceiling: {rendered}")
        object.__setattr__(self, "allowed_effects", normalized)

    @classmethod
    def for_mode(
        cls,
        accepted_turn_id: str,
        mode: ExecutionPolicyMode | str,
    ) -> "ExecutionPolicy":
        """Freeze the safest complete capability set for *mode*."""
        normalized_mode = ExecutionPolicyMode.parse(mode)
        return cls(
            accepted_turn_id=accepted_turn_id,
            mode=normalized_mode,
            allowed_effects=_POLICY_MODE_CEILINGS[normalized_mode],
        )

    def to_dict(self) -> dict[str, object]:
        """Return the canonical, versioned persistence representation."""
        return {
            "schema_version": 1,
            "accepted_turn_id": self.accepted_turn_id,
            "mode": self.mode.value,
            "allowed_effects": sorted(str(effect) for effect in self.allowed_effects),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ExecutionPolicy":
        """Restore and validate a persisted accepted-turn policy."""
        if not isinstance(data, Mapping):
            raise TypeError("execution policy must be a mapping")
        if data.get("schema_version") != 1:
            raise ValueError(
                f"Unsupported execution policy schema: {data.get('schema_version')!r}"
            )
        allowed_effects = data.get("allowed_effects")
        if not isinstance(allowed_effects, list) or not all(
            isinstance(effect, str) for effect in allowed_effects
        ):
            raise ValueError("execution policy allowed_effects must be a list of strings")
        return cls(
            accepted_turn_id=data.get("accepted_turn_id"),
            mode=data.get("mode"),
            allowed_effects=normalize_effects(allowed_effects),
        )

    def narrow(
        self,
        allowed_effects: EffectInput | Iterable[EffectInput] | None,
        *,
        mode: ExecutionPolicyMode | str | None = None,
    ) -> "ExecutionPolicy":
        """Return a set-intersection policy; reject every widening attempt."""
        requested = normalize_effects(allowed_effects)
        widening = {
            effect
            for effect in requested
            if not any(
                _effect_is_within(effect, current)
                for current in self.allowed_effects
            )
        }
        if widening:
            rendered = ", ".join(sorted(map(str, widening)))
            raise PolicyWideningError(f"Cannot widen accepted-turn effects: {rendered}")

        target_mode = self.mode if mode is None else ExecutionPolicyMode.parse(mode)
        current_ceiling = _POLICY_MODE_CEILINGS[self.mode]
        target_ceiling = _POLICY_MODE_CEILINGS[target_mode]
        if any(
            not any(_effect_is_within(effect, current) for current in current_ceiling)
            for effect in target_ceiling
        ):
            raise PolicyWideningError(
                f"Cannot widen policy mode from {self.mode.value} to {target_mode.value}"
            )

        intersection = {
            common
            for current in self.allowed_effects
            for desired in requested
            if (common := _effect_intersection(current, desired)) is not None
        }
        return ExecutionPolicy(
            accepted_turn_id=self.accepted_turn_id,
            mode=target_mode,
            allowed_effects=frozenset(intersection),
        )


def execution_policy_for_permission_mode(
    accepted_turn_id: str,
    permission_mode: str,
) -> ExecutionPolicy:
    """Freeze one accepted-turn policy from the legacy permission mode.

    Realtor Beta has a draft-only cohort maximum. Its engineering ``default``
    remains read-only; only explicit edit/bypass-style modes reach the
    draft-only ceiling. Unknown modes always raise.
    """
    if not isinstance(permission_mode, str):
        raise TypeError("permission_mode must be a string")
    normalized = permission_mode.strip()
    try:
        policy_mode = PERMISSION_MODE_POLICY_MODES[normalized]
    except KeyError as exc:
        raise ValueError(f"Unknown permission mode: {permission_mode!r}") from exc

    if _beta_approval_policy_active():
        policy_mode = _BETA_PERMISSION_MODE_POLICY_MODES[normalized]
    return ExecutionPolicy.for_mode(accepted_turn_id, policy_mode)


_current_execution_policy: contextvars.ContextVar[Optional[ExecutionPolicy]] = (
    contextvars.ContextVar("current_execution_policy", default=None)
)
_current_execution_policy_revision: contextvars.ContextVar[Optional[int]] = (
    contextvars.ContextVar("current_execution_policy_revision", default=None)
)


@dataclass(frozen=True, slots=True)
class ExecutionPolicyContextToken:
    """Tokens required to restore one policy-and-revision context binding."""

    policy_token: contextvars.Token[Optional[ExecutionPolicy]]
    revision_token: contextvars.Token[Optional[int]]


def set_current_execution_policy(
    policy: ExecutionPolicy,
    *,
    policy_revision: Optional[int] = None,
) -> ExecutionPolicyContextToken:
    """Bind one validated durable policy and its receipt revision."""
    if not isinstance(policy, ExecutionPolicy):
        raise TypeError("current execution policy must be an ExecutionPolicy")
    if policy_revision is not None and (
        isinstance(policy_revision, bool) or not isinstance(policy_revision, int)
    ):
        raise TypeError("current execution policy revision must be an integer")
    if policy_revision is not None and policy_revision < 0:
        raise ValueError("current execution policy revision cannot be negative")

    policy_token = _current_execution_policy.set(policy)
    try:
        revision_token = _current_execution_policy_revision.set(policy_revision)
    except BaseException:
        _current_execution_policy.reset(policy_token)
        raise
    return ExecutionPolicyContextToken(policy_token, revision_token)


def reset_current_execution_policy(
    token: ExecutionPolicyContextToken,
) -> None:
    """Restore the worker's prior policy and receipt-revision binding."""
    if not isinstance(token, ExecutionPolicyContextToken):
        raise TypeError("invalid execution policy context token")
    _current_execution_policy_revision.reset(token.revision_token)
    _current_execution_policy.reset(token.policy_token)


def get_current_execution_policy() -> Optional[ExecutionPolicy]:
    """Return the bound durable policy, or ``None`` outside an accepted turn."""
    return _current_execution_policy.get()


def get_current_execution_policy_revision() -> Optional[int]:
    """Return the bound durable receipt revision, if one was supplied."""
    return _current_execution_policy_revision.get()


@dataclass(frozen=True, slots=True)
class EffectAuthorization:
    """Auditable result from the pure effect-policy evaluator."""

    allowed: bool
    accepted_turn_id: Optional[str]
    requested_effects: frozenset[Effect]
    denied_effects: frozenset[Effect]
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def authorize_effects(
    policy: Optional[ExecutionPolicy],
    effects: EffectInput | Iterable[EffectInput] | None,
) -> EffectAuthorization:
    """Evaluate effects against one frozen policy without mutating runtime state.

    Missing, empty, malformed, and explicitly unknown effect declarations all
    become ``unknown`` and are denied.  This makes restricted plan/read-only/
    draft-only calls fail closed while leaving live dispatch unchanged until
    its adapters explicitly invoke this evaluator.
    """
    try:
        requested = normalize_effects(effects)
    except Exception:
        requested = frozenset({Effect(EffectKind.UNKNOWN)})
    if not requested:
        requested = frozenset({Effect(EffectKind.UNKNOWN)})

    if not isinstance(policy, ExecutionPolicy):
        return EffectAuthorization(
            allowed=False,
            accepted_turn_id=None,
            requested_effects=requested,
            denied_effects=requested,
            reason="missing_policy" if policy is None else "invalid_policy",
        )

    unknown = {effect for effect in requested if effect.kind is EffectKind.UNKNOWN}
    denied = {
        effect
        for effect in requested
        if effect.kind is EffectKind.UNKNOWN
        or not any(
            _effect_is_within(effect, capability)
            for capability in policy.allowed_effects
        )
    }
    if unknown:
        reason = "unknown_effect"
    elif denied:
        reason = "effect_not_allowed"
    else:
        reason = "allowed"
    return EffectAuthorization(
        allowed=not denied,
        accepted_turn_id=policy.accepted_turn_id,
        requested_effects=requested,
        denied_effects=frozenset(denied),
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Permission mode (Claude-style): default | acceptEdits | plan | bypassPermissions
# ---------------------------------------------------------------------------
# `plan` is the security-relevant mode: a read-only session where the runtime
# BLOCKS every state-changing tool (file writes, mutating shell commands,
# message sends, sub-agent delegation, computer-use, browser actions) so the
# agent can only research and produce a written plan. The user "approves" by
# leaving plan mode (the /run command or the Settings picker), which flips the
# session back to `default` and lets the agent execute.
#
# Modes are session-scoped (set via /plan, /run, --plan, or the desktop
# picker) and fall back to the config default `approvals.permission_mode`.
# This is the function run_agent imports to drive the plan-mode system prompt
# AND the runtime tool gate; before it existed the import silently failed and
# plan mode was a no-op.
_VALID_PERMISSION_MODES = frozenset(
    {"default", "acceptEdits", "plan", "bypassPermissions"}
)
_session_permission_mode: dict[str, str] = {}
_config_pmode_cache: Optional[str] = None

# Tools that are read-only / side-effect-free and therefore allowed in plan
# mode. Default-DENY: anything not in this set (and not a read-only terminal
# command or a memory/skill READ) is blocked. New/unknown tools are blocked by
# default — the safe posture for a "read-only" guarantee.
PLAN_MODE_READ_ONLY_TOOLS = frozenset({
    "read_file", "search_files",            # file / code inspection
    "web_search", "web_extract", "web_fetch",  # web research
    "vision_analyze",                       # image analysis, no state change
    "session_search", "skill_view", "skills_list",  # session / skill inspection
    "ha_get_state", "ha_list_entities", "ha_list_services",  # home-assistant reads
    "todo", "clarify", "present_plan",      # planning + asking the user
})
_PLAN_MEMORY_READ_ACTIONS = frozenset(
    {"get", "search", "recall", "list", "view", "read", "show"}
)
_PLAN_SKILL_READ_ACTIONS = frozenset({"view", "list", "search", "show", "read"})

# Shell verbs/operators that mutate state — block in plan mode even though the
# `terminal` tool is otherwise allowed for read-only inspection (ls, cat, grep,
# git status/log/diff, find, ps, head, tail, wc, which). Conservative denylist;
# when in doubt the command is treated as mutating. The existing hardline +
# dangerous-command floor still runs underneath, so this only needs to catch
# ordinary mutations.
_PLAN_MUTATING_SHELL = re.compile(
    r"""(?:^|\s|&&|\|\||;|`|\()(?:
        rm|rmdir|mv|cp|install|ln|mkdir|touch|tee|truncate|dd|shred|xargs|
        chmod|chown|chgrp|chflags|
        sed\s+-i|perl\s+-i|awk\s+-i|
        kill|pkill|killall|
        sudo|su|
        launchctl|systemctl|service|crontab|defaults\s+write|
        mount|umount|diskutil|
        npm|pnpm|yarn|pip|pip3|poetry|brew|apt|apt-get|gem|cargo|
        docker|kubectl|terraform|
        curl|wget|nc|ncat|ssh|scp|sftp|rsync|
        go\s+(?:install|build|run|get)|
        git\s+(?:commit|push|add|reset|clean|checkout|merge|rebase|stash|rm|mv|tag|apply|restore|init|fetch|pull|cherry-pick)
    )(?:\s|$)""",
    re.VERBOSE,
)
# find/xargs mutation flags (-delete, -exec ...).
_PLAN_MUTATING_FLAGS = re.compile(r"(?:^|\s)-(?:delete|exec|execdir)\b")
# Redirect that writes a real file (allow 2>/dev/null, >/dev/null, 2>&1).
_PLAN_WRITE_REDIRECT = re.compile(r">\s*(?!/dev/null\b|&)")


def set_session_permission_mode(session_key: str, mode: str) -> str:
    """Set the permission mode for one session. Returns the normalized mode."""
    if not isinstance(mode, str):
        raise TypeError("permission mode must be a string")
    mode = mode.strip()
    if mode not in _VALID_PERMISSION_MODES:
        raise ValueError(f"Unknown permission mode: {mode!r}")
    if session_key:
        with _lock:
            _session_permission_mode[session_key] = mode
    return mode


def _config_permission_mode() -> str:
    """Config default `approvals.permission_mode`, cached for the process.

    Cached so the runtime gate (runs on every tool call) never pays a config
    file read; a session-scoped /plan or /run override bypasses this entirely.
    """
    global _config_pmode_cache
    if _config_pmode_cache is None:
        try:
            mode = (_get_approval_config().get("permission_mode") or "default").strip()
        except Exception:
            mode = "default"
        _config_pmode_cache = mode if mode in _VALID_PERMISSION_MODES else "default"
    return _config_pmode_cache


def get_session_permission_mode(session_key: str) -> str:
    """Return the session's permission mode, falling back to the config default."""
    if session_key:
        with _lock:
            mode = _session_permission_mode.get(session_key)
        if mode:
            return mode
    return _config_permission_mode()


def get_session_permission_mode_for_policy(session_key: str) -> str:
    """Return the unsanitized accepted-turn input permission mode.

    Unlike the legacy runtime getter, this does not turn an unknown configured
    value into permissive ``default``. The strict policy mapper will reject it.
    A missing value still means the documented default mode.
    """
    if session_key:
        with _lock:
            mode = _session_permission_mode.get(session_key)
        if mode is not None:
            return mode
    try:
        configured = _get_approval_config().get("permission_mode")
    except Exception:
        configured = None
    if configured is None:
        return "default"
    if not isinstance(configured, str):
        raise TypeError("configured permission mode must be a string")
    configured = configured.strip()
    return configured or "default"


def get_permission_mode() -> str:
    """Permission mode for the *current* approval session (contextvar-scoped)."""
    return get_session_permission_mode(get_current_session_key(default=""))


def _is_plan_safe_terminal(command: str) -> bool:
    """True when a shell command is read-only enough to allow in plan mode."""
    if not command or not command.strip():
        return True
    norm = _normalize_command_for_detection(command)
    if detect_hardline_command(norm)[0]:
        return False
    if detect_dangerous_command(norm)[0]:
        return False
    if _PLAN_WRITE_REDIRECT.search(norm):
        return False
    if _PLAN_MUTATING_FLAGS.search(norm):
        return False
    if _PLAN_MUTATING_SHELL.search(norm):
        return False
    return True


def _plan_block_message(what: str) -> str:
    return (
        f"BLOCKED (plan mode): {what} is a state-changing action and plan mode "
        "is read-only. Keep researching with read-only tools and finish your "
        "written plan. When it's ready, tell the user to approve it — they "
        "leave plan mode (the /run command or the permission picker) and you "
        "execute it then."
    )


def plan_mode_block(function_name: str, function_args) -> Optional[str]:
    """Return a block message when a tool call is disallowed in plan mode.

    Returns None when plan mode is off OR the call is read-only (allowed).
    Default-deny: any tool not explicitly known read-only is blocked.
    """
    if get_permission_mode() != "plan":
        return None
    name = function_name or ""
    args = function_args if isinstance(function_args, dict) else {}

    if name in PLAN_MODE_READ_ONLY_TOOLS:
        return None
    if name == "terminal":
        cmd = args.get("command") or args.get("cmd") or args.get("script") or ""
        if isinstance(cmd, str) and _is_plan_safe_terminal(cmd):
            return None
        return _plan_block_message("running a shell command that may change state")
    if name == "memory":
        if str(args.get("action") or "").lower() in _PLAN_MEMORY_READ_ACTIONS:
            return None
        return _plan_block_message("a memory write")
    if name == "skill_manage":
        if str(args.get("action") or "").lower() in _PLAN_SKILL_READ_ACTIONS:
            return None
        return _plan_block_message("a skill change")
    # Unknown / explicitly-mutating tool (write_file, patch, browser_*,
    # computer, delegate_task, send_*, …): block by default.
    return _plan_block_message(f"the '{name}' tool")


def is_approved(session_key: str, pattern_key: str) -> bool:
    """Check if a pattern is approved (session-scoped or permanent).

    Accept both the current canonical key and the legacy regex-derived key so
    existing command_allowlist entries continue to work after key migrations.
    """
    aliases = _approval_key_aliases(pattern_key)
    with _lock:
        if any(alias in _permanent_approved for alias in aliases):
            return True
        session_approvals = _session_approved.get(session_key, set())
        return any(alias in session_approvals for alias in aliases)


def approve_permanent(pattern_key: str):
    """Add a pattern to the permanent allowlist."""
    with _lock:
        _permanent_approved.add(pattern_key)


def load_permanent(patterns: set):
    """Bulk-load permanent allowlist entries from config."""
    with _lock:
        _permanent_approved.update(patterns)



# =========================================================================
# Config persistence for permanent allowlist
# =========================================================================

def load_permanent_allowlist() -> set:
    """Load permanently allowed command patterns from config.

    Also syncs them into the approval module so is_approved() works for
    patterns added via 'always' in a previous session.
    """
    try:
        from elevate_cli.config import load_config
        config = load_config()
        patterns = set(config.get("command_allowlist", []) or [])
        if patterns:
            load_permanent(patterns)
        return patterns
    except Exception as e:
        logger.warning("Failed to load permanent allowlist: %s", e)
        return set()


def save_permanent_allowlist(patterns: set):
    """Save permanently allowed command patterns to config."""
    try:
        from elevate_cli.config import load_config, save_config
        config = load_config()
        config["command_allowlist"] = list(patterns)
        save_config(config)
    except Exception as e:
        logger.warning("Could not save allowlist: %s", e)


# =========================================================================
# Approval prompting + orchestration
# =========================================================================

def prompt_dangerous_approval(command: str, description: str,
                              timeout_seconds: int | None = None,
                              allow_permanent: bool = True,
                              approval_callback=None) -> str:
    """Prompt the user to approve a dangerous command (CLI only).

    Args:
        allow_permanent: When False, hide the [a]lways option (used when
            tirith warnings are present, since broad permanent allowlisting
            is inappropriate for content-level security findings).
        approval_callback: Optional callback registered by the CLI for
            prompt_toolkit integration. Signature:
            (command, description, *, allow_permanent=True) -> str.

    Returns: 'once', 'session', 'always', or 'deny'
    """
    if timeout_seconds is None:
        timeout_seconds = _get_approval_timeout()

    if approval_callback is not None:
        try:
            return approval_callback(command, description,
                                     allow_permanent=allow_permanent)
        except Exception as e:
            logger.error("Approval callback failed: %s", e, exc_info=True)
            return "deny"

    # Fail-closed guard: if prompt_toolkit owns the terminal (interactive
    # CLI session) and no approval callback is registered on this thread,
    # the input() fallback below would spawn a daemon thread whose read
    # can never see Enter -- the user's keystrokes go to prompt_toolkit,
    # not input(), producing an invisible 60s deadlock (issue #15216).
    # Deny fast and log loudly instead so the caller can surface a real
    # error to the agent. Any thread that needs interactive approval must
    # install a callback via tools.terminal_tool.set_approval_callback()
    # before reaching this point (see delegate_tool.py, run_agent.py
    # _execute_tool_calls_concurrent / _spawn_background_review for the
    # established pattern).
    try:
        from prompt_toolkit.application.current import get_app_or_none
        if get_app_or_none() is not None:
            logger.warning(
                "Dangerous-command approval requested on a thread with no "
                "approval callback while prompt_toolkit is active; denying "
                "to avoid stdin deadlock. command=%r description=%r",
                command, description,
            )
            return "deny"
    except Exception:
        # prompt_toolkit not installed, or detection failed -- fall through
        # to the legacy input() path (safe in non-TUI contexts: scripts,
        # tests, sshd, etc.).
        pass

    os.environ["ELEVATE_SPINNER_PAUSE"] = "1"
    try:
        # Resolve the active UI language once per prompt so we don't re-read
        # config/YAML inside the retry loop below.
        from agent.i18n import t
        while True:
            print()
            print(f"  {t('approval.dangerous_header', description=description)}")
            print(f"      {command}")
            print()
            if allow_permanent:
                print(t("approval.choose_long"))
            else:
                print(t("approval.choose_short"))
            print()
            sys.stdout.flush()

            result = {"choice": ""}

            def get_input():
                try:
                    prompt = t("approval.prompt_long") if allow_permanent else t("approval.prompt_short")
                    result["choice"] = input(prompt).strip().lower()
                except (EOFError, OSError):
                    result["choice"] = ""

            thread = threading.Thread(target=get_input, daemon=True)
            thread.start()
            thread.join(timeout=timeout_seconds)

            if thread.is_alive():
                print("\n" + t("approval.timeout"))
                return "deny"

            choice = result["choice"]
            if choice in {'o', 'once'}:
                print(t("approval.allowed_once"))
                return "once"
            elif choice in {'s', 'session'}:
                print(t("approval.allowed_session"))
                return "session"
            elif choice in {'a', 'always'}:
                if not allow_permanent:
                    print(t("approval.allowed_session"))
                    return "session"
                print(t("approval.allowed_always"))
                return "always"
            else:
                print(t("approval.denied"))
                return "deny"

    except (EOFError, KeyboardInterrupt):
        print("\n" + t("approval.cancelled"))
        return "deny"
    finally:
        if "ELEVATE_SPINNER_PAUSE" in os.environ:
            del os.environ["ELEVATE_SPINNER_PAUSE"]
        print()
        sys.stdout.flush()


def _normalize_approval_mode(mode) -> str:
    """Normalize approval mode values loaded from YAML/config.

    YAML 1.1 treats bare words like `off` as booleans, so a config entry like
    `approvals:\n  mode: off` is parsed as False unless quoted. Treat that as the
    intended string mode instead of falling back to manual approvals.
    """
    if isinstance(mode, bool):
        return "off" if mode is False else "manual"
    if isinstance(mode, str):
        normalized = mode.strip().lower()
        return normalized or "manual"
    return "manual"


def _get_approval_config() -> dict:
    """Read the approvals config block. Returns a dict with 'mode', 'timeout', etc."""
    try:
        from elevate_cli.config import load_config
        config = load_config()
        return config.get("approvals", {}) or {}
    except Exception as e:
        logger.warning("Failed to load approval config: %s", e)
        return {}


def _get_approval_mode() -> str:
    """Read the approval mode from config. Returns 'manual', 'smart', or 'off'."""
    mode = _get_approval_config().get("mode", "manual")
    normalized = _normalize_approval_mode(mode)
    # Exact Beta never treats stale ``approvals.mode=off`` state as an
    # authorization decision.  Stable keeps its long-standing compatibility.
    if _beta_approval_policy_active() and normalized == "off":
        return "manual"
    return normalized


def _get_approval_timeout() -> int:
    """Read the approval timeout from config. Defaults to 60 seconds."""
    try:
        return int(_get_approval_config().get("timeout", 60))
    except (ValueError, TypeError):
        return 60


def _get_cron_approval_mode() -> str:
    """Read the cron approval mode from config. Returns 'deny' or 'approve'."""
    # There is no human present to approve a dangerous unattended action.
    # Exact Beta therefore ignores every legacy allow alias.
    if _beta_approval_policy_active():
        return "deny"
    try:
        from elevate_cli.config import load_config
        config = load_config()
        mode = str(cfg_get(config, "approvals", "cron_mode", default="deny")).lower().strip()
        if mode in {"approve", "off", "allow", "yes"}:
            return "approve"
        return "deny"
    except Exception:
        return "deny"


def _approval_bypass_enabled(approval_mode: Optional[str] = None) -> bool:
    """Return whether a legacy approval bypass is active for this call.

    Exact Realtor Beta has no approval bypass surface.  Reading all inputs
    behind this single policy gate prevents an old environment variable,
    session flag, config file, or permission-mode selection from silently
    re-enabling dangerous command execution.
    """
    if _beta_approval_policy_active():
        return False
    return bool(
        is_truthy_value(os.getenv("ELEVATE_YOLO_MODE"))
        or is_current_session_yolo_enabled()
        or approval_mode == "off"
        or (
            approval_mode is not None
            and get_permission_mode() == "bypassPermissions"
        )
    )


def _cron_dangerous_block_result(description: str) -> dict:
    """Build the fail-closed result for an unattended dangerous command."""
    if _beta_approval_policy_active():
        guidance = (
            "Realtor Beta does not allow dangerous commands in unattended "
            "cron jobs. Run the action interactively so a person can review it."
        )
    else:
        guidance = (
            "Find an alternative approach that avoids this command. To allow "
            "dangerous commands in cron jobs, set approvals.cron_mode: approve "
            "in config.yaml."
        )
    return {
        "approved": False,
        "message": (
            f"BLOCKED: Command flagged as dangerous ({description}) but cron "
            f"jobs run without a user present to approve it. {guidance}"
        ),
    }


def _smart_approve(command: str, description: str) -> str:
    """Use the auxiliary LLM to assess risk and decide approval.

    Returns 'approve' if the LLM determines the command is safe,
    'deny' if genuinely dangerous, or 'escalate' if uncertain.

    Inspired by OpenAI Codex's Smart Approvals guardian subagent
    (openai/codex#13860).
    """
    try:
        from agent.auxiliary_client import call_llm

        prompt = f"""You are a security reviewer for an AI coding agent. A terminal command was flagged by pattern matching as potentially dangerous.

Command: {command}
Flagged reason: {description}

Assess the ACTUAL risk of this command. Many flagged commands are false positives — for example, `python -c "print('hello')"` is flagged as "script execution via -c flag" but is completely harmless.

Rules:
- APPROVE if the command is clearly safe (benign script execution, safe file operations, development tools, package installs, git operations, etc.)
- DENY if the command could genuinely damage the system (recursive delete of important paths, overwriting system files, fork bombs, wiping disks, dropping databases, etc.)
- ESCALATE if you're uncertain

Respond with exactly one word: APPROVE, DENY, or ESCALATE"""

        response = call_llm(
            task="approval",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=16,
        )

        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if not (
            isinstance(finish_reason, str)
            and finish_reason.strip().lower() == "stop"
        ):
            return "escalate"

        answer = (choice.message.content or "").strip().upper()

        if answer == "APPROVE":
            return "approve"
        elif answer == "DENY":
            return "deny"
        else:
            return "escalate"

    except Exception as e:
        logger.debug("Smart approvals: LLM call failed (%s), escalating", e)
        return "escalate"


def check_dangerous_command(command: str, env_type: str,
                            approval_callback=None) -> dict:
    """Check if a command is dangerous and handle approval.

    This is the main entry point called by terminal_tool before executing
    any command. It orchestrates detection, session checks, and prompting.

    Args:
        command: The shell command to check.
        env_type: Terminal backend type ('local', 'ssh', 'docker', etc.).
        approval_callback: Optional CLI callback for interactive prompts.

    Returns:
        {"approved": True/False, "message": str or None, ...}
    """
    if env_type in {"docker", "singularity", "modal", "daytona", "vercel_sandbox"}:
        return {"approved": True, "message": None}

    # Hardline floor: commands with no recovery path (rm -rf /, mkfs, dd
    # to raw device, shutdown/reboot, fork bomb, kill -1) are blocked
    # unconditionally, BEFORE the yolo bypass.  Opting into yolo is
    # trusting the agent with your files and services, not trusting it
    # to wipe the disk or power the box off.
    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        logger.warning("Hardline block: %s (command: %s)", hardline_desc, command[:200])
        return _hardline_block_result(hardline_desc)

    # Stable supports process- and session-scoped YOLO. Exact Beta ignores
    # both through the central bypass policy gate.
    if _approval_bypass_enabled():
        return {"approved": True, "message": None}

    is_dangerous, pattern_key, description = detect_dangerous_command(command)
    if not is_dangerous:
        return {"approved": True, "message": None}

    session_key = get_current_session_key()
    if is_approved(session_key, pattern_key):
        return {"approved": True, "message": None}

    is_cli = env_var_enabled("ELEVATE_INTERACTIVE")
    is_gateway = _is_gateway_approval_context()

    if not is_cli and not is_gateway:
        # Cron sessions: respect cron_mode config
        if env_var_enabled("ELEVATE_CRON_SESSION"):
            if _get_cron_approval_mode() == "deny":
                return _cron_dangerous_block_result(description)
        return {"approved": True, "message": None}

    if is_gateway or env_var_enabled("ELEVATE_EXEC_ASK"):
        submit_pending(session_key, {
            "command": command,
            "pattern_key": pattern_key,
            "description": description,
        })
        return {
            "approved": False,
            "pattern_key": pattern_key,
            "status": "approval_required",
            "command": command,
            "description": description,
            "message": (
                f"⚠️ This command is potentially dangerous ({description}). "
                f"Asking the user for approval.\n\n**Command:**\n```\n{command}\n```"
            ),
        }

    choice = prompt_dangerous_approval(command, description,
                                       approval_callback=approval_callback)

    if choice == "deny":
        return {
            "approved": False,
            "message": f"BLOCKED: User denied this potentially dangerous command (matched '{description}' pattern). Do NOT retry this command - the user has explicitly rejected it.",
            "pattern_key": pattern_key,
            "description": description,
        }

    if choice == "session":
        approve_session(session_key, pattern_key)
    elif choice == "always":
        approve_session(session_key, pattern_key)
        approve_permanent(pattern_key)
        save_permanent_allowlist(_permanent_approved)

    return {"approved": True, "message": None}


# =========================================================================
# Combined pre-exec guard (tirith + dangerous command detection)
# =========================================================================

def _format_tirith_description(tirith_result: dict) -> str:
    """Build a human-readable description from tirith findings.

    Includes severity, title, and description for each finding so users
    can make an informed approval decision.
    """
    findings = tirith_result.get("findings") or []
    if not findings:
        summary = tirith_result.get("summary") or "security issue detected"
        return f"Security scan: {summary}"

    parts = []
    for f in findings:
        severity = f.get("severity", "")
        title = f.get("title", "")
        desc = f.get("description", "")
        if title and desc:
            parts.append(f"[{severity}] {title}: {desc}" if severity else f"{title}: {desc}")
        elif title:
            parts.append(f"[{severity}] {title}" if severity else title)
    if not parts:
        summary = tirith_result.get("summary") or "security issue detected"
        return f"Security scan: {summary}"

    return "Security scan — " + "; ".join(parts)


def check_all_command_guards(command: str, env_type: str,
                             approval_callback=None) -> dict:
    """Run all pre-exec security checks and return a single approval decision.

    Gathers findings from tirith and dangerous-command detection, then
    presents them as a single combined approval request. This prevents
    a gateway force=True replay from bypassing one check when only the
    other was shown to the user.
    """
    # Skip containers for both checks
    if env_type in {"docker", "singularity", "modal", "daytona", "vercel_sandbox"}:
        return {"approved": True, "message": None}

    # Hardline floor: unconditional block for catastrophic commands
    # (rm -rf /, mkfs, dd to raw device, shutdown/reboot, fork bomb,
    # kill -1). Applies BEFORE yolo / mode=off / cron approve-mode so
    # no session-level setting can bypass it.
    is_hardline, hardline_desc = detect_hardline_command(command)
    if is_hardline:
        logger.warning("Hardline block: %s (command: %s)", hardline_desc, command[:200])
        return _hardline_block_result(hardline_desc)

    # == Sudo stdin guard ==
    # Like the hardline floor above, this is unconditional: there is never a
    # legitimate reason for the agent to pipe passwords to sudo -S when no
    # SUDO_PASSWORD has been configured.  This must fire BEFORE the yolo
    # check so even yolo/smart approval/mode=off cannot bypass it.
    is_sudo_guess, sudo_guess_desc = _check_sudo_stdin_guard(command)
    if is_sudo_guess:
        logger.warning("Sudo stdin guard block: %s (command: %s)",
                       sudo_guess_desc, command[:200])
        return _sudo_stdin_block_result(sudo_guess_desc)

    # Stable supports process/session YOLO, approvals.mode=off, and
    # bypassPermissions. Exact Beta ignores all four behind one policy gate.
    # The hardline + sudo-stdin floors above still run before this.
    approval_mode = _get_approval_mode()
    if _approval_bypass_enabled(approval_mode):
        return {"approved": True, "message": None}

    is_cli = env_var_enabled("ELEVATE_INTERACTIVE")
    is_gateway = _is_gateway_approval_context()
    is_ask = env_var_enabled("ELEVATE_EXEC_ASK")

    # Preserve the existing non-interactive behavior: outside CLI/gateway/ask
    # flows, we do not block on approvals and we skip external guard work.
    if not is_cli and not is_gateway and not is_ask:
        # Cron sessions: respect cron_mode config
        if env_var_enabled("ELEVATE_CRON_SESSION"):
            if _get_cron_approval_mode() == "deny":
                # Run detection to get a description for the block message
                is_dangerous, _pk, description = detect_dangerous_command(command)
                if is_dangerous:
                    return _cron_dangerous_block_result(description)
        return {"approved": True, "message": None}

    # --- Phase 1: Gather findings from both checks ---

    # Tirith check — wrapper guarantees no raise for expected failures.
    # Only catch ImportError (module not installed).
    tirith_result = {"action": "allow", "findings": [], "summary": ""}
    try:
        from tools.tirith_security import check_command_security
        tirith_result = check_command_security(command)
    except ImportError:
        pass  # tirith module not installed — allow

    # Dangerous command check (detection only, no approval)
    is_dangerous, pattern_key, description = detect_dangerous_command(command)

    # --- Phase 2: Decide ---

    # Collect warnings that need approval
    warnings = []  # list of (pattern_key, description, is_tirith)

    session_key = get_current_session_key()

    # Tirith block/warn → approvable warning with rich findings.
    # Previously, tirith "block" was a hard block with no approval prompt.
    # Now both block and warn go through the approval flow so users can
    # inspect the explanation and approve if they understand the risk.
    if tirith_result["action"] in {"block", "warn"}:
        findings = tirith_result.get("findings") or []
        rule_id = findings[0].get("rule_id", "unknown") if findings else "unknown"
        tirith_key = f"tirith:{rule_id}"
        tirith_desc = _format_tirith_description(tirith_result)
        if not is_approved(session_key, tirith_key):
            warnings.append((tirith_key, tirith_desc, True))

    if is_dangerous:
        if not is_approved(session_key, pattern_key):
            warnings.append((pattern_key, description, False))

    # Nothing to warn about
    if not warnings:
        return {"approved": True, "message": None}

    # --- Phase 2.5: Smart approval (auxiliary LLM risk assessment) ---
    # When approvals.mode=smart, ask the aux LLM before prompting the user.
    # Inspired by OpenAI Codex's Smart Approvals guardian subagent
    # (openai/codex#13860).
    if approval_mode == "smart":
        combined_desc_for_llm = "; ".join(desc for _, desc, _ in warnings)
        verdict = _smart_approve(command, combined_desc_for_llm)
        if verdict == "approve":
            # Auto-approve and grant session-level approval for these patterns
            for key, _, _ in warnings:
                approve_session(session_key, key)
            logger.debug("Smart approval: auto-approved '%s' (%s)",
                         command[:60], combined_desc_for_llm)
            return {"approved": True, "message": None,
                    "smart_approved": True,
                    "description": combined_desc_for_llm}
        elif verdict == "deny":
            combined_desc_for_llm = "; ".join(desc for _, desc, _ in warnings)
            return {
                "approved": False,
                "message": f"BLOCKED by smart approval: {combined_desc_for_llm}. "
                           "The command was assessed as genuinely dangerous. Do NOT retry.",
                "smart_denied": True,
            }
        # verdict == "escalate" → fall through to manual prompt

    # --- Phase 3: Approval ---

    # Combine descriptions for a single approval prompt
    combined_desc = "; ".join(desc for _, desc, _ in warnings)
    primary_key = warnings[0][0]
    all_keys = [key for key, _, _ in warnings]
    has_tirith = any(is_t for _, _, is_t in warnings)

    # Gateway/async approval — block the agent thread until the user
    # responds with /approve or /deny, mirroring the CLI's synchronous
    # input() flow.  The agent never sees "approval_required"; it either
    # gets the command output (approved) or a definitive "BLOCKED" message.
    if is_gateway or is_ask:
        notify_cb = None
        with _lock:
            notify_cb = _gateway_notify_cbs.get(session_key)

        if notify_cb is not None:
            # --- Blocking gateway approval (queue-based) ---
            # Each call gets its own _ApprovalEntry so parallel subagents
            # and execute_code threads can block concurrently.
            approval_data = {
                "command": command,
                "pattern_key": primary_key,
                "pattern_keys": all_keys,
                "description": combined_desc,
                "correlation_id": _current_approval_correlation_id(),
            }
            entry = _ApprovalEntry(approval_data)
            with _lock:
                _gateway_queues.setdefault(session_key, []).append(entry)

            # Notify plugins that an approval is being requested. Fires before
            # the gateway notify callback so observers (e.g. macOS notifier
            # plugins, audit logs, Slack alerts) get the event in real time.
            _fire_approval_hook(
                "pre_approval_request",
                command=command,
                description=combined_desc,
                pattern_key=primary_key,
                pattern_keys=list(all_keys),
                session_key=session_key,
                surface="gateway",
                request_id=entry.request_id,
                correlation_id=entry.correlation_id,
            )

            # Notify the user (bridges sync agent thread → async gateway)
            try:
                notify_cb(entry.data)
            except Exception as exc:
                logger.warning("Gateway approval notify failed: %s", exc)
                with _lock:
                    queue = _gateway_queues.get(session_key, [])
                    if entry in queue:
                        queue.remove(entry)
                    if not queue:
                        _gateway_queues.pop(session_key, None)
                    entry.result = "deny"
                    entry.resolution_reason = "notify_failed"
                    entry.event.set()
                _record_approval_receipt(
                    entry,
                    session_key,
                    outcome="deny",
                    reason=entry.resolution_reason,
                )
                return {
                    "approved": False,
                    "message": "BLOCKED: Failed to send approval request to user. Do NOT retry.",
                    "pattern_key": primary_key,
                    "description": combined_desc,
                }

            # The UI notification stays ahead of best-effort disk I/O so a
            # cold recorder import cannot delay or hide the approval prompt.
            _record_approval_event(
                "approval.requested",
                entry,
                session_key,
                outcome="pending",
                reason="dangerous_command",
            )

            # Block until the user responds or timeout (default 5 min).
            # Poll in short slices so we can fire activity heartbeats every
            # ~10s to the agent's inactivity tracker.  Without this, the
            # blocking event.wait() never touches activity, and the
            # gateway's inactivity watchdog (agent.gateway_timeout, default
            # 1800s) kills the agent while the user is still responding to
            # the approval prompt.  Mirrors the _wait_for_process() cadence
            # in tools/environments/base.py.
            timeout = _get_approval_config().get("gateway_timeout", 300)
            try:
                timeout = int(timeout)
            except (ValueError, TypeError):
                timeout = 300

            try:
                from tools.environments.base import touch_activity_if_due
            except Exception:  # pragma: no cover
                touch_activity_if_due = None

            _now = time.monotonic()
            _deadline = _now + max(timeout, 0)
            _activity_state = {"last_touch": _now, "start": _now}
            resolved = False
            while True:
                _remaining = _deadline - time.monotonic()
                if _remaining <= 0:
                    break
                # 1s poll slice — the event is set immediately when the
                # user responds, so slice length only controls heartbeat
                # cadence, not user-visible responsiveness.
                if entry.event.wait(timeout=min(1.0, _remaining)):
                    resolved = True
                    break
                if touch_activity_if_due is not None:
                    touch_activity_if_due(
                        _activity_state, "waiting for user approval"
                    )

            # Clean up this entry from the queue
            with _lock:
                queue = _gateway_queues.get(session_key, [])
                if entry in queue:
                    queue.remove(entry)
                    entry.resolution_reason = "wait_timeout"
                if not queue:
                    _gateway_queues.pop(session_key, None)

            choice = entry.result
            if choice is not None and entry.event.is_set():
                resolved = True
            # Normalize outcome for the post hook. Unresolved (timeout) and
            # None both mean the user never responded; report that explicitly
            # so plugins can distinguish timeout from explicit deny.
            _outcome = (
                "timeout" if not resolved
                else (choice if choice else "timeout")
            )
            if _outcome == "timeout":
                # A concurrent resolver/cleanup publishes its reason while
                # holding the same lock.  Only supply the timeout fallback
                # when this waiter won removal at the deadline.
                entry.resolution_reason = entry.resolution_reason or "wait_timeout"
            _record_approval_receipt(
                entry,
                session_key,
                outcome=_outcome,
                reason=entry.resolution_reason or "user_response",
            )
            _fire_approval_hook(
                "post_approval_response",
                command=command,
                description=combined_desc,
                pattern_key=primary_key,
                pattern_keys=list(all_keys),
                session_key=session_key,
                surface="gateway",
                choice=_outcome,
                request_id=entry.request_id,
                correlation_id=entry.correlation_id,
            )

            if not resolved or choice is None or choice == "deny":
                if not resolved or choice is None:
                    reason = "timed out"
                elif entry.resolution_reason in {
                    "gateway_unregistered",
                    "session_cleared",
                    "session_interrupted",
                    "session_stopped",
                }:
                    reason = "cancelled because the approval session ended"
                else:
                    reason = "denied by user"
                return {
                    "approved": False,
                    "message": f"BLOCKED: Command {reason}. Do NOT retry this command.",
                    "pattern_key": primary_key,
                    "description": combined_desc,
                }

            # User approved — persist based on scope (same logic as CLI)
            for key, _, is_tirith in warnings:
                if choice == "session" or (choice == "always" and is_tirith):
                    approve_session(session_key, key)
                elif choice == "always":
                    approve_session(session_key, key)
                    approve_permanent(key)
                    save_permanent_allowlist(_permanent_approved)
                # choice == "once": no persistence — command allowed this
                # single time only, matching the CLI's behavior.

            return {"approved": True, "message": None,
                    "user_approved": True, "description": combined_desc}

        # Fallback: no gateway callback registered (e.g. cron, batch).
        # Return approval_required for backward compat.
        submit_pending(session_key, {
            "command": command,
            "pattern_key": primary_key,
            "pattern_keys": all_keys,
            "description": combined_desc,
        })
        return {
            "approved": False,
            "pattern_key": primary_key,
            "status": "pending_approval",
            "approval_pending": True,
            "command": command,
            "description": combined_desc,
            "message": (
                f"⚠️ {combined_desc}. Asking the user for approval.\n\n**Command:**\n```\n{command}\n```"
            ),
        }

    # CLI interactive: single combined prompt
    # Hide [a]lways when any tirith warning is present
    _fire_approval_hook(
        "pre_approval_request",
        command=command,
        description=combined_desc,
        pattern_key=primary_key,
        pattern_keys=list(all_keys),
        session_key=session_key,
        surface="cli",
    )
    choice = prompt_dangerous_approval(command, combined_desc,
                                       allow_permanent=not has_tirith,
                                       approval_callback=approval_callback)
    _fire_approval_hook(
        "post_approval_response",
        command=command,
        description=combined_desc,
        pattern_key=primary_key,
        pattern_keys=list(all_keys),
        session_key=session_key,
        surface="cli",
        choice=choice,
    )

    if choice == "deny":
        return {
            "approved": False,
            "message": "BLOCKED: User denied. Do NOT retry.",
            "pattern_key": primary_key,
            "description": combined_desc,
        }

    # Persist approval for each warning individually
    for key, _, is_tirith in warnings:
        if choice == "session" or (choice == "always" and is_tirith):
            # tirith: session only (no permanent broad allowlisting)
            approve_session(session_key, key)
        elif choice == "always":
            # dangerous patterns: permanent allowed
            approve_session(session_key, key)
            approve_permanent(key)
            save_permanent_allowlist(_permanent_approved)

    return {"approved": True, "message": None,
            "user_approved": True, "description": combined_desc}


# Load permanent allowlist from config on module import
load_permanent_allowlist()
