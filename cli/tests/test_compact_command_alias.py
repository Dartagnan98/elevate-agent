"""`/compact` is the sole compaction command (industry-standard, like Claude
Code / Codex). `/compress` was removed entirely (no alias) to avoid a duplicate
command. The old `/compact` display-mode toggle moved to `/compactview`.
"""
import inspect

from elevate_cli.commands import resolve_command, GATEWAY_KNOWN_COMMANDS


def test_compact_is_canonical():
    d = resolve_command("compact")
    assert d is not None and d.name == "compact"
    assert "compact" in d.description.lower()


def test_compress_is_removed():
    assert resolve_command("compress") is None, "/compress must be gone (no alias)"
    assert "compress" not in GATEWAY_KNOWN_COMMANDS


def test_compact_known_to_gateway():
    assert "compact" in GATEWAY_KNOWN_COMMANDS


def test_gateway_dispatch_targets_compact_only():
    import tui_gateway.server as srv
    src = inspect.getsource(srv)
    assert '_cmd_base == "compact"' in src
    assert 'name == "compact"' in src
    # no leftover alias tuple
    assert 'in ("compact", "compress")' not in src


def test_compact_display_toggle_renamed_to_compactview():
    import tui_gateway.server as srv
    src = inspect.getsource(srv)
    assert '"/compactview"' in src
    assert '("/compact", "Toggle compact display mode", "TUI")' not in src
