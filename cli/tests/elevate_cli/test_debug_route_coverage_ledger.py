"""Route-family coverage ledger guard.

The debugging epic requires every route family to have a contract test or an
explicit readiness gap. This keeps known caller-without-contract gaps visible.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
EPIC_PATH = REPO_ROOT / "cli/docs/epic-desktop-debugging-routes-2026-06-18.md"
WEB_SERVER_PATH = REPO_ROOT / "cli/elevate_cli/web_server.py"
API_TS_PATH = REPO_ROOT / "cli/web/src/lib/api.ts"
CLI_TESTS_ROOT = REPO_ROOT / "cli/tests"

MISSING_CONTRACT_FAMILIES = [
    {
        "family": "composio",
        "route_marker": "/api/composio/",
        "caller_marker": "getComposioStatus",
    },
    {
        "family": "ayrshare",
        "route_marker": "/api/ayrshare/",
        "caller_marker": "getAyrshareStatus",
    },
    {
        "family": "social",
        "route_marker": "/api/social/",
        "caller_marker": "getSocialSnapshot",
    },
    {
        "family": "integrations",
        "route_marker": "/api/integrations",
        "caller_marker": "getIntegrations",
    },
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _cli_test_text() -> str:
    chunks: list[str] = []
    for path in sorted(CLI_TESTS_ROOT.rglob("*.py")):
        if path == Path(__file__):
            continue
        chunks.append(_read(path))
    return "\n".join(chunks)


def test_missing_local_route_contract_ledger_is_current():
    epic = _read(EPIC_PATH)
    web_server = _read(WEB_SERVER_PATH)
    api_ts = _read(API_TS_PATH)
    test_text = _cli_test_text()

    for row in MISSING_CONTRACT_FAMILIES:
        family = row["family"]
        route_marker = row["route_marker"]
        caller_marker = row["caller_marker"]

        assert route_marker in web_server, f"{family} route marker missing"
        assert caller_marker in api_ts, f"{family} caller marker missing"
        assert route_marker not in test_text, (
            f"{family} now has a cli/tests contract; update the missing-contract ledger"
        )
        assert f"- `{family}`:" in epic, f"{family} explicit gap missing from epic"
