"""Overlay deployment must satisfy desktop startup without running old UI."""

import importlib.util
from pathlib import Path
import re

import pytest


spec = importlib.util.spec_from_file_location(
    "deploy_web_overlay", Path(__file__).parents[2] / "scripts/deploy_web_overlay.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def make_build(root, name):
    (root / "assets").mkdir(parents=True)
    (root / "assets" / name).write_text(name)
    (root / "index.html").write_text(
        f'<html><head><script src="/assets/{name}"></script></head></html>'
    )


def test_deploy_keeps_desktop_refs_and_runs_only_new_entry(tmp_path):
    built, overlay, packaged = [tmp_path / name for name in ("built", "overlay", "packaged")]
    make_build(built, "index-new.js")
    make_build(packaged, "index-old.js")
    module.deploy(built, overlay, packaged)
    index = (overlay / "index.html").read_text()
    scripts = re.findall(r'<script src="([^"]+)"', index)
    assert len(scripts) == 1
    assert scripts[0].endswith("/index-new.js")
    assert (overlay / scripts[0].lstrip("/")).read_text() == "index-new.js"
    assert "assets/index-old.js" in index
    assert (overlay / "assets/index-old.js").read_text() == "index-old.js"
    module.deploy(built, overlay, packaged)
    assert (overlay / "index.html").read_text() == index


def test_preserves_existing_overlay_compatibility_entry(tmp_path):
    built, overlay, packaged = [tmp_path / name for name in ("built", "overlay", "packaged")]
    make_build(built, "index-new.js")
    make_build(packaged, "index-old.js")
    make_build(overlay, "index-old.js")
    (packaged / "assets/index-old.js").unlink()
    module.deploy(built, overlay, packaged)
    assert (overlay / "assets/index-old.js").read_text() == "index-old.js"


def test_incomplete_build_does_not_replace_live_index(tmp_path):
    built, overlay, packaged = [tmp_path / name for name in ("built", "overlay", "packaged")]
    make_build(built, "index-new.js")
    make_build(packaged, "index-old.js")
    make_build(overlay, "index-live.js")
    original = (overlay / "index.html").read_bytes()
    (built / "assets/index-new.js").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        module.deploy(built, overlay, packaged)
    assert (overlay / "index.html").read_bytes() == original


def test_changed_bytes_get_new_urls_even_when_chunk_names_are_unchanged(tmp_path):
    built, overlay, packaged = [tmp_path / name for name in ("built", "overlay", "packaged")]
    make_build(built, "index-new.js")
    make_build(packaged, "index-old.js")
    (built / "assets/index-new.js").write_text(
        'const deps=["assets/hook.js"];import("./hook.js");'
    )
    hook = built / "assets/hook.js"
    hook.write_text('export const value="first";')
    module.deploy(built, overlay, packaged)
    first = re.search(r'<script src="([^"]+)"', (overlay / "index.html").read_text())[1]
    first_entry = overlay / first.lstrip("/")
    first_hook = first_entry.parent / "hook.js"
    assert first_hook.read_text() == 'export const value="first";'
    assert f'"{first_entry.parent.relative_to(overlay)}/hook.js"' in first_entry.read_text()
    assert 'import("./hook.js")' in first_entry.read_text()
    hook.write_text('export const value="second";')
    module.deploy(built, overlay, packaged)
    second = re.search(r'<script src="([^"]+)"', (overlay / "index.html").read_text())[1]
    assert first != second
    assert first_hook.read_text() == 'export const value="first";'
    assert (overlay / second.lstrip("/")).parent.joinpath("hook.js").read_text() == 'export const value="second";'
