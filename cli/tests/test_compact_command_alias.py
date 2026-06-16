"""`/compact` is the canonical compaction command; `/compress` is a back-compat alias.

Aligns Elevate with the industry-standard `/compact` (Claude Code, Codex, etc.).
The old `/compact` display-mode toggle moved to `/compactview`.
"""
from elevate_cli.commands import resolve_command, GATEWAY_KNOWN_COMMANDS


def test_compact_is_canonical():
    d = resolve_command("compact")
    assert d is not None and d.name == "compact"
    assert "compact" in d.description.lower()


def test_compress_resolves_to_compact_alias():
    d = resolve_command("compress")
    assert d is not None and d.name == "compact", "/compress must alias to /compact"


def test_both_names_known_to_gateway():
    assert "compact" in GATEWAY_KNOWN_COMMANDS
    assert "compress" in GATEWAY_KNOWN_COMMANDS  # alias still accepted


def test_gateway_dispatch_accepts_both_names():
    # the gateway slash.exec / command.dispatch paths string-match the bare verb;
    # both must route to the compaction handler.
    import tui_gateway.server as srv
    src = __import__("inspect").getsource(srv)
    assert '_cmd_base in ("compact", "compress")' in src
    assert 'name in ("compact", "compress")' in src
    assert '"compact"' in src and '"compress"' in src  # _MUTATES_WHILE_RUNNING


def test_compact_display_toggle_renamed_to_compactview():
    # the old display-mode toggle no longer squats on /compact
    import tui_gateway.server as srv
    src = __import__("inspect").getsource(srv)
    assert '"/compactview"' in src
    assert '("/compact", "Toggle compact display mode", "TUI")' not in src
