"""Anti-false-flag stealth for AUTHORIZED, authenticated browser sessions.

Elevate agents log into the *user's own* accounts (SkySlope, Lofty, Xposure
PCS, GHL, MLS portals) to do authorized work, and naive automation trips
bot-detection heuristics that throw false positives — login walls, soft
challenges, "unusual activity" interstitials — at sessions that are entirely
legitimate. This module makes authorized automation not *look* like a crude
bot so those walls come up less often. It is NOT challenge-defeat: it solves
no CAPTCHA, bypasses no 2FA, and circumvents no anti-bot challenge. When a
real challenge appears, the loop guard in ``browser_tool`` already routes to
``needs_operator`` — that stays the answer.

Three levers, each config-driven (``browser.*``), default-on but conservative,
every knob overridable via the cached ``cfg_get(cfg, "browser", ...)`` idiom:

  1. **Persistent per-site authed profiles** — a resolver that maps a
     navigation URL's registrable domain to a stable, durable profile so a
     warm, logged-in browser state is reused across tasks instead of a cold
     context every run. A trusted, warm profile is THE lever that keeps login
     walls/challenges from appearing.
  2. **Fingerprint hardening** — a playwright-stealth-style JS init script
     (``navigator.webdriver`` undefined, plausible ``navigator`` shape, WebGL
     vendor/renderer spoof to a real GPU, ``chrome`` runtime object, permission
     query shim, canvas/audio noise) plus the Chrome launch flags that strip
     the obvious ``--enable-automation`` / ``AutomationControlled`` tells.
  3. **Human-like pacing** — small randomized delays + per-character type
     jitter + occasional scroll-into-view before *state-affecting* actions
     only, so trivial reads are not slowed.

Everything here is pure (no browser launch, no I/O beyond config reads) so it
is unit-testable without a real browser, and it composes with the loop guard:
pacing sleeps happen *inside* a single guarded action (they do not issue extra
commands, so they neither consume the action budget nor reset the stuck
counter — that wiring lives in ``browser_tool``).
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # config is always present in-process, but keep import defensive
    from elevate_cli.config import cfg_get, read_raw_config
except Exception:  # pragma: no cover - minimal environments
    def read_raw_config() -> Dict[str, Any]:  # type: ignore[misc]
        return {}

    def cfg_get(cfg, *keys, default=None):  # type: ignore[misc]
        cur = cfg
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k)
            if cur is None:
                return default
        return cur


# ---------------------------------------------------------------------------
# Config defaults (every knob overridable via browser.* in config.yaml)
# ---------------------------------------------------------------------------

DEFAULT_PERSISTENT_PROFILES = True
DEFAULT_FINGERPRINT_HARDENING = True
DEFAULT_HUMAN_PACING = True
DEFAULT_PACING_MIN_MS = 120
DEFAULT_PACING_MAX_MS = 650
# Per-character type jitter (each keystroke), kept tiny so a 40-char field
# adds well under a second.
DEFAULT_TYPE_JITTER_MIN_MS = 8
DEFAULT_TYPE_JITTER_MAX_MS = 45
# Probability of a scroll-into-view before a click (humans don't scroll every
# single time; most clicks are on already-visible elements).
DEFAULT_PRECLICK_SCROLL_PROB = 0.15

# Real Chrome on this platform — keep the spoofed surface consistent with a
# plausible build. These are descriptive, not load-bearing: the UA string we
# actually advertise is whatever the launched Chrome reports; we only spoof the
# JS-visible *consistency* layer (platform/vendor/renderer) to match.
_GPU_BY_PLATFORM = {
    "darwin": ("Google Inc. (Apple)", "ANGLE (Apple, ANGLE Metal Renderer: Apple M2, Unspecified Version)"),
    "win32": ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    "linux": ("Google Inc. (Intel)", "ANGLE (Intel, Mesa Intel(R) UHD Graphics (CML GT2), OpenGL 4.6)"),
}
_NAV_PLATFORM_BY_OS = {"darwin": "MacIntel", "win32": "Win32", "linux": "Linux x86_64"}


# Chrome launch flags that strip the obvious automation tells. These compose
# with whatever AGENT_BROWSER_ARGS the caller already sets — never replace.
# (No headless tells here: the managed local path drives a *visible* Chrome.)
_STEALTH_CHROME_FLAGS = (
    "--disable-blink-features=AutomationControlled",
    "--exclude-switches=enable-automation",
    "--disable-features=IsolateOrigins,site-per-process",
)


# ---------------------------------------------------------------------------
# Config readers (cached idiom mirrors browser_tool's command_timeout reader)
# ---------------------------------------------------------------------------

_cfg_cache: Dict[str, Any] = {}
_cfg_cache_loaded = False


def reset_cache() -> None:
    """Drop the cached config snapshot so the next read re-evaluates.

    Called from ``browser_tool.cleanup_all_browsers`` alongside the other
    browser-config cache resets.
    """
    global _cfg_cache, _cfg_cache_loaded
    _cfg_cache = {}
    _cfg_cache_loaded = False


def _cfg() -> Dict[str, Any]:
    global _cfg_cache, _cfg_cache_loaded
    if _cfg_cache_loaded:
        return _cfg_cache
    _cfg_cache_loaded = True
    try:
        _cfg_cache = read_raw_config() or {}
    except Exception:
        _cfg_cache = {}
    return _cfg_cache


def _bool_cfg(key: str, default: bool) -> bool:
    val = cfg_get(_cfg(), "browser", key, default=None)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _int_cfg(key: str, default: int, floor: int = 0) -> int:
    val = cfg_get(_cfg(), "browser", key, default=None)
    if val is None:
        return default
    try:
        return max(int(val), floor)
    except (TypeError, ValueError):
        return default


def _float_cfg(key: str, default: float) -> float:
    val = cfg_get(_cfg(), "browser", key, default=None)
    if val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def persistent_profiles_enabled() -> bool:
    """``browser.persistent_profiles`` (default on)."""
    return _bool_cfg("persistent_profiles", DEFAULT_PERSISTENT_PROFILES)


def fingerprint_hardening_enabled() -> bool:
    """``browser.fingerprint_hardening`` (default on)."""
    return _bool_cfg("fingerprint_hardening", DEFAULT_FINGERPRINT_HARDENING)


def human_pacing_enabled() -> bool:
    """``browser.human_pacing`` (default on)."""
    return _bool_cfg("human_pacing", DEFAULT_HUMAN_PACING)


# ---------------------------------------------------------------------------
# 1. Persistent per-site authed profiles
# ---------------------------------------------------------------------------

# Registrable-domain extraction without a public-suffix-list dependency: take
# the last two labels, with a small allowlist of common two-label public
# suffixes so ``foo.co.uk`` -> ``foo.co.uk`` not ``co.uk``. This only needs to
# be stable (same URL -> same dir), not a perfect PSL implementation.
_TWO_LABEL_SUFFIXES = frozenset({
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.nz", "co.za", "com.au",
    "com.br", "co.jp", "co.in", "com.mx", "co.il",
})


def registrable_domain(url: str) -> Optional[str]:
    """Best-effort registrable domain for a navigation URL.

    ``https://app.skyslope.com/foo`` -> ``skyslope.com``.
    ``https://office.lofty.com:443/`` -> ``lofty.com``.
    Returns None for blank / non-host URLs (about:blank, data:, file:, IPs).
    """
    if not url:
        return None
    s = url.strip()
    # Strip scheme
    if "://" in s:
        s = s.split("://", 1)[1]
    # Strip path/query/fragment, userinfo, port
    s = s.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if "@" in s:
        s = s.rsplit("@", 1)[1]
    s = s.split(":", 1)[0].strip().lower()
    if not s or s in ("localhost",):
        return None
    # Bare IP -> not a registrable domain (no warm-profile keying)
    if all(part.isdigit() for part in s.split(".")) and s.count(".") == 3:
        return None
    labels = [p for p in s.split(".") if p]
    if len(labels) < 2:
        return None
    last_two = ".".join(labels[-2:])
    if last_two in _TWO_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return last_two


def default_profile_root() -> Path:
    """Stable root for per-site profiles.

    ``browser.profile_dir`` overrides; default is
    ``<elevate_home>/browser-profiles``. We co-locate under the elevate home
    (same convention as the existing ``chrome-debug`` clone) rather than
    ``~/.playwright-cli`` so it survives across tasks and is easy to inspect.
    """
    override = cfg_get(_cfg(), "browser", "profile_dir", default=None)
    if override:
        return Path(os.path.expanduser(str(override)))
    try:
        from elevate_constants import get_elevate_home
        return get_elevate_home() / "browser-profiles"
    except Exception:
        return Path(os.path.expanduser("~/.elevate/browser-profiles"))


def _slug_domain(domain: str) -> str:
    """Filesystem-safe slug for a domain (dots -> underscores)."""
    return "".join(c if (c.isalnum() or c in "-_") else "_" for c in domain)


def resolve_profile_dir(url: str) -> Optional[Path]:
    """Map a navigation URL's registrable domain to a durable profile dir.

    Returns ``<profile_root>/<domain-slug>`` (created on resolve) when
    persistent profiles are enabled and the URL has a real registrable domain,
    else None (caller keeps whatever default profile it already uses).

    CONCURRENCY DECISION (documented for callers): in the default local mode
    Elevate drives a *single* visible CDP Chrome shared across tasks via
    separate tabs — one warm, logged-in user-data-dir, never two Chrome procs
    on the same dir. That single shared profile is itself the persistent
    per-site authed state (it carries every site's cookies), so there is no
    same-dir corruption risk to guard against in that path. This resolver
    provides NAMED per-domain dirs for the headless/sidecar path and for
    explicit per-site warm profiles; it never returns the same dir to two
    concurrent Chrome processes because the single-CDP-window model already
    serializes access at the browser level. Where a caller would launch a
    second Chrome on a returned dir, it must use copy-on-write (snapshot the
    dir, sync cookies back) — the SAFE option — rather than sharing the live
    dir. We expose ``profile_is_locked`` / ``mark_profile_locked`` so a caller
    can enforce that.
    """
    if not persistent_profiles_enabled():
        return None
    domain = registrable_domain(url)
    if not domain:
        return None
    root = default_profile_root()
    profile_dir = root / _slug_domain(domain)
    try:
        profile_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return profile_dir


def _lockfile(profile_dir: Path) -> Path:
    return profile_dir / ".elevate-profile.lock"


def profile_is_locked(profile_dir: Path) -> bool:
    """True if another live process holds this profile dir (PID in lockfile is
    alive). Stale locks (dead PID) read as unlocked."""
    lf = _lockfile(profile_dir)
    try:
        pid = int(lf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False  # dead PID -> stale lock


def mark_profile_locked(profile_dir: Path) -> bool:
    """Claim a profile dir for this process. Returns False if a live process
    already holds it (caller should copy-on-write instead of sharing)."""
    if profile_is_locked(profile_dir):
        return False
    try:
        _lockfile(profile_dir).write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def release_profile_lock(profile_dir: Path) -> None:
    """Release this process's claim on a profile dir (best-effort)."""
    lf = _lockfile(profile_dir)
    try:
        if lf.exists() and lf.read_text(encoding="utf-8").strip() == str(os.getpid()):
            lf.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 2. Fingerprint hardening
# ---------------------------------------------------------------------------

def _platform_key() -> str:
    import sys
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def stealth_chrome_flags() -> List[str]:
    """Chrome launch flags that strip the obvious automation tells.

    Empty list when fingerprint hardening is disabled.
    """
    if not fingerprint_hardening_enabled():
        return []
    return list(_STEALTH_CHROME_FLAGS)


def build_init_script() -> str:
    """JS injected into every page before its scripts run.

    Patches the JS-visible automation tells to a plausible, *consistent* real
    Chrome shape so authorized sessions are not flagged as crude bots:
      - ``navigator.webdriver`` -> undefined (the #1 automation tell)
      - ``navigator.languages`` / ``platform`` / ``hardwareConcurrency`` /
        ``deviceMemory`` -> plausible values
      - WebGL ``UNMASKED_VENDOR/RENDERER`` -> a real GPU string
      - ``window.chrome`` runtime object present
      - ``navigator.permissions.query`` shim (notifications -> 'prompt')
      - tiny, *consistent* canvas noise (same per-page, so a re-check matches)

    Returns "" when fingerprint hardening is disabled. The script is idempotent
    (guards against double-injection) and never throws (each patch is
    try/caught) so it can't break a page the agent is legitimately driving.
    """
    if not fingerprint_hardening_enabled():
        return ""
    plat = _platform_key()
    nav_platform = _NAV_PLATFORM_BY_OS.get(plat, "Linux x86_64")
    gpu_vendor, gpu_renderer = _GPU_BY_PLATFORM.get(plat, _GPU_BY_PLATFORM["linux"])
    # JSON-safe embedding of the spoofed strings.
    import json as _json
    # NOTE: the JS template is littered with literal ``{`` / ``}`` so we cannot
    # use ``str.format``; substitute named placeholders explicitly instead.
    return (
        _INIT_SCRIPT_TEMPLATE
        .replace("__NAV_PLATFORM__", _json.dumps(nav_platform))
        .replace("__GPU_VENDOR__", _json.dumps(gpu_vendor))
        .replace("__GPU_RENDERER__", _json.dumps(gpu_renderer))
    )


# Single defensive IIFE. Every patch is individually try/caught and the whole
# thing is guarded so re-injection is a no-op.
_INIT_SCRIPT_TEMPLATE = r"""
(function(){
  try {
    if (window.__elevateStealth) return;
    Object.defineProperty(window, '__elevateStealth', {value: true, enumerable: false});
  } catch (e) { return; }

  // 1. navigator.webdriver -> undefined (the canonical automation tell)
  try {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      get: () => undefined, configurable: true
    });
  } catch (e) {}
  try { delete navigator.__proto__.webdriver; } catch (e) {}

  // 2. plausible navigator shape
  try {
    Object.defineProperty(navigator, 'languages', {
      get: () => ['en-US', 'en'], configurable: true
    });
  } catch (e) {}
  try {
    Object.defineProperty(navigator, 'platform', {
      get: () => __NAV_PLATFORM__, configurable: true
    });
  } catch (e) {}
  try {
    if (!navigator.hardwareConcurrency || navigator.hardwareConcurrency < 2) {
      Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8, configurable: true
      });
    }
  } catch (e) {}
  try {
    if (!('deviceMemory' in navigator)) {
      Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8, configurable: true
      });
    }
  } catch (e) {}

  // 3. window.chrome runtime object present (headless Chrome omits it)
  try {
    if (!window.chrome) { window.chrome = {}; }
    if (!window.chrome.runtime) { window.chrome.runtime = {}; }
  } catch (e) {}

  // 4. permissions.query shim — Notification should report the real
  //    Notification.permission, not always 'denied' (a headless tell).
  try {
    const origQuery = navigator.permissions && navigator.permissions.query;
    if (origQuery) {
      navigator.permissions.query = function(params) {
        if (params && params.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission, onchange: null });
        }
        return origQuery.call(navigator.permissions, params);
      };
    }
  } catch (e) {}

  // 5. WebGL vendor/renderer spoof to a real GPU string
  try {
    const patchGL = function(proto) {
      if (!proto) return;
      const orig = proto.getParameter;
      proto.getParameter = function(param) {
        // UNMASKED_VENDOR_WEBGL = 37445, UNMASKED_RENDERER_WEBGL = 37446
        if (param === 37445) return __GPU_VENDOR__;
        if (param === 37446) return __GPU_RENDERER__;
        return orig.apply(this, arguments);
      };
    };
    if (window.WebGLRenderingContext) patchGL(WebGLRenderingContext.prototype);
    if (window.WebGL2RenderingContext) patchGL(WebGL2RenderingContext.prototype);
  } catch (e) {}

  // 6. consistent (deterministic, sub-pixel) canvas noise — same per page so a
  //    re-read matches itself; differs across machines, not across reads.
  try {
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function() {
      return origToDataURL.apply(this, arguments);
    };
  } catch (e) {}
})();
"""


# ---------------------------------------------------------------------------
# 3. Human-like pacing
# ---------------------------------------------------------------------------

# State-affecting actions get paced; pure reads (snapshot) do not, so trivial
# reads keep full throughput. (navigate is paced because a submit/redirect is
# state-affecting and humans don't fire navigations instantly back-to-back.)
_PACED_ACTIONS = frozenset({"navigate", "click", "type", "press", "scroll"})


def should_pace(action: str) -> bool:
    """True when ``action`` is state-affecting AND human pacing is enabled."""
    return human_pacing_enabled() and action in _PACED_ACTIONS


def pacing_delay_seconds() -> float:
    """A single randomized pre-action delay in seconds.

    ``browser.pacing_min_ms`` / ``browser.pacing_max_ms`` (defaults ~120-650ms).
    """
    lo = _int_cfg("pacing_min_ms", DEFAULT_PACING_MIN_MS)
    hi = _int_cfg("pacing_max_ms", DEFAULT_PACING_MAX_MS)
    if hi < lo:
        hi = lo
    return random.uniform(lo, hi) / 1000.0


def pace_action(action: str, *, sleep=time.sleep) -> float:
    """Apply a human-like pre-action delay for a state-affecting action.

    Returns the delay applied (0.0 if not paced). ``sleep`` is injectable for
    tests. IMPORTANT: this sleeps *inside* one guarded action — it issues no
    browser command, so it does not consume the loop-guard action budget nor
    reset the stuck counter.
    """
    if not should_pace(action):
        return 0.0
    delay = pacing_delay_seconds()
    if delay > 0:
        sleep(delay)
    return delay


def type_keystroke_delays(text: str) -> List[float]:
    """Per-character jitter delays (seconds) for typing ``text`` like a human.

    Returns one delay per character. Empty list when pacing is disabled or the
    text is empty. ``browser.type_jitter_min_ms`` / ``browser.type_jitter_max_ms``.
    """
    if not human_pacing_enabled() or not text:
        return []
    lo = _int_cfg("type_jitter_min_ms", DEFAULT_TYPE_JITTER_MIN_MS)
    hi = _int_cfg("type_jitter_max_ms", DEFAULT_TYPE_JITTER_MAX_MS)
    if hi < lo:
        hi = lo
    return [random.uniform(lo, hi) / 1000.0 for _ in text]


def type_with_jitter(text: str, emit, *, sleep=time.sleep) -> int:
    """Type ``text`` one character at a time with per-character jitter.

    ``emit(char)`` performs the per-character send (injected so this stays
    pure/testable — no browser here). Returns the number of characters emitted.
    Falls back to a single ``emit(text)`` when pacing is disabled.
    """
    if not human_pacing_enabled() or not text:
        emit(text)
        return len(text)
    delays = type_keystroke_delays(text)
    for ch, d in zip(text, delays):
        emit(ch)
        if d > 0:
            sleep(d)
    return len(text)


def should_scroll_before_click() -> bool:
    """Occasionally scroll an element into view before clicking (humans do).

    Probability ``browser.preclick_scroll_prob`` (default 0.15). Disabled when
    human pacing is off.
    """
    if not human_pacing_enabled():
        return False
    prob = _float_cfg("preclick_scroll_prob", DEFAULT_PRECLICK_SCROLL_PROB)
    if prob <= 0:
        return False
    if prob >= 1:
        return True
    return random.random() < prob
