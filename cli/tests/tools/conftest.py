"""Shared fixtures for tests/tools/ web-provider tests.

Per-file subprocess isolation means each test file gets a fresh interpreter,
so module-level state (like the web-search-provider registry) is empty when
a file starts.  The ``web_registry_populated`` fixture registers all bundled
providers before each test and resets the registry afterwards — tests that
depend on the registry being populated should use it explicitly or via
``@pytest.mark.usefixtures("web_registry_populated")``.
"""

import sys
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _browser_loop_guard_isolation(monkeypatch):
    """Keep the browser loop guard hermetic across tests.

    The loop guard in ``tools.browser_tool`` tracks per-task fingerprints and
    action budgets in module state and emits fire-and-forget telemetry via the
    operational DB. In tests that hammer the same task_id (SSRF/policy tests
    navigate repeatedly), that would (a) leak stuck counters between tests and
    (b) spawn telemetry threads that try to boot the embedded Postgres. Clear
    the state and no-op the DB writer around every test. Individual tests can
    re-patch ``_write_stuck_telemetry`` to observe telemetry.
    """
    bt = sys.modules.get("tools.browser_tool")
    if bt is not None:
        monkeypatch.setattr(bt, "_write_stuck_telemetry", lambda *a, **k: None)
        with bt._loop_guard_lock:
            bt._loop_guard_state.clear()
        # Neutralize anti-false-flag stealth so its (legitimate, default-on)
        # pacing delays + occasional pre-click scroll-into-view don't slow
        # tests or perturb exact ``_run_browser_command`` call counts. Stealth
        # has its own dedicated tests; here we measure the loop guard / command
        # layer. A test that wants stealth re-enables it explicitly.
        stealth = sys.modules.get("tools.browser_stealth")
        if stealth is not None:
            stealth.reset_cache()
            stealth._cfg_cache = {"browser": {
                "human_pacing": False,
                "fingerprint_hardening": False,
                "persistent_profiles": False,
            }}
            stealth._cfg_cache_loaded = True
    yield
    bt = sys.modules.get("tools.browser_tool")
    if bt is not None:
        with bt._loop_guard_lock:
            bt._loop_guard_state.clear()
    stealth = sys.modules.get("tools.browser_stealth")
    if stealth is not None:
        stealth.reset_cache()


def register_all_web_providers():
    """Register all bundled web-search providers into the global registry.

    This is the single source of truth for the provider list used by
    test classes that need the registry populated for dispatch checks.
    """
    from agent.web_search_registry import register_provider, _reset_for_tests
    from plugins.web.brave_free.provider import BraveFreeWebSearchProvider
    from plugins.web.ddgs.provider import DDGSWebSearchProvider
    from plugins.web.exa.provider import ExaWebSearchProvider
    from plugins.web.firecrawl.provider import FirecrawlWebSearchProvider
    from plugins.web.parallel.provider import ParallelWebSearchProvider
    from plugins.web.searxng.provider import SearXNGWebSearchProvider
    from plugins.web.tavily.provider import TavilyWebSearchProvider
    from plugins.web.xai.provider import XAIWebSearchProvider

    _reset_for_tests()
    for cls in (
        BraveFreeWebSearchProvider,
        DDGSWebSearchProvider,
        ExaWebSearchProvider,
        FirecrawlWebSearchProvider,
        ParallelWebSearchProvider,
        SearXNGWebSearchProvider,
        TavilyWebSearchProvider,
        XAIWebSearchProvider,
    ):
        register_provider(cls())


@pytest.fixture
def web_registry_populated():
    """Populate the web-search-provider registry for one test, then reset."""
    register_all_web_providers()
    yield
    from agent.web_search_registry import _reset_for_tests
    _reset_for_tests()


@pytest.fixture
def disable_lazy_stt_install():
    """Disarm the runtime lazy-install probe so static ``_HAS_FASTER_WHISPER``
    patches accurately simulate 'faster-whisper not installed'.

    Without this, ``_try_lazy_install_stt()`` calls
    ``importlib.util.find_spec("faster_whisper")``, which returns truthy
    whenever the package is installed in the dev / CI environment —
    defeating the test's ``_HAS_FASTER_WHISPER=False`` patch.

    Opt in at module scope with
    ``pytestmark = pytest.mark.usefixtures("disable_lazy_stt_install")``.
    """
    with patch("tools.transcription_tools._try_lazy_install_stt", return_value=False):
        yield
