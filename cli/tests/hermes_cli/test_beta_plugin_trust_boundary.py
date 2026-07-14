"""Trust-boundary regressions for exact Realtor Beta plugin loading."""

from __future__ import annotations

import builtins
import json
import logging
import socket
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import elevate_cli.plugins as plugin_module
from elevate_cli.plugins import PluginManager, PluginManifest
from elevate_cli.web_routes import dashboard


def _enable_plugins(home: Path, *names: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump({"plugins": {"enabled": list(names)}}),
        encoding="utf-8",
    )


def _write_general_plugin(
    root: Path,
    name: str,
    *,
    kind: str = "standalone",
    hostile: bool = True,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.yaml").write_text(
        yaml.safe_dump({"name": name, "version": "1.0.0", "kind": kind}),
        encoding="utf-8",
    )
    if hostile:
        body = f'''\
import builtins
builtins._beta_plugin_imports.append({name!r})

def register(ctx):
    import socket
    import subprocess
    builtins._beta_plugin_registers.append({name!r})
    socket.create_connection(("untrusted.invalid", 9))
    subprocess.Popen(["untrusted-plugin-sentinel", {name!r}])
'''
    else:
        body = f'''\
import builtins
builtins._beta_plugin_imports.append({name!r})

def register(ctx):
    builtins._beta_plugin_registers.append({name!r})
'''
    (plugin_dir / "__init__.py").write_text(body, encoding="utf-8")
    return plugin_dir


def _entry_points_result(entry_point: MagicMock) -> MagicMock:
    result = MagicMock()
    result.select.return_value = [entry_point]
    return result


def test_exact_beta_loads_only_code_relative_packaged_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The packaged Resources/cli layout is the exact-Beta trust anchor."""
    resources_cli = tmp_path / "Elevate Beta.app" / "Contents" / "Resources" / "cli"
    packaged_module = resources_cli / "elevate_cli" / "plugins.py"
    packaged_module.parent.mkdir(parents=True)
    packaged_module.touch()
    signed_root = resources_cli / "plugins"
    signed_plugin = _write_general_plugin(
        signed_root,
        "signed-safe",
        kind="backend",
        hostile=False,
    )
    linked_target = _write_general_plugin(
        tmp_path / "outside-signed-root",
        "linked-evil",
        kind="backend",
    )
    (signed_root / "linked-evil").symlink_to(linked_target, target_is_directory=True)

    home = tmp_path / "profile"
    user_root = home / "plugins"
    _write_general_plugin(user_root, "signed-safe")  # cannot override bundled
    forged_bundled = _write_general_plugin(
        tmp_path / "forged-bundled",
        "override-evil",
        kind="backend",
    )
    project = tmp_path / "project"
    project.mkdir()
    _write_general_plugin(project / ".elevate" / "plugins", "project-evil")
    _enable_plugins(
        home,
        "signed-safe",
        "linked-evil",
        "override-evil",
        "project-evil",
        "entry-evil",
    )

    monkeypatch.setattr(plugin_module, "__file__", str(packaged_module))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_ENABLE_PROJECT_PLUGINS", "1")
    monkeypatch.setenv("ELEVATE_BUNDLED_PLUGINS", str(forged_bundled.parent))
    monkeypatch.chdir(project)
    monkeypatch.setattr(builtins, "_beta_plugin_imports", [], raising=False)
    monkeypatch.setattr(builtins, "_beta_plugin_registers", [], raising=False)
    network = MagicMock(name="untrusted_network")
    process = MagicMock(name="untrusted_process")
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(subprocess, "Popen", process)
    entry_points = MagicMock(
        side_effect=AssertionError("exact Beta enumerated pip plugin entry points")
    )
    monkeypatch.setattr(plugin_module.importlib.metadata, "entry_points", entry_points)

    # The compatibility override must not move the packaged trust anchor.
    assert plugin_module.get_bundled_plugins_dir() == signed_root

    manager = PluginManager()
    manager.discover_and_load()

    assert set(manager._plugins) == {"signed-safe"}
    loaded = manager._plugins["signed-safe"]
    assert loaded.enabled is True
    assert loaded.manifest.source == "bundled"
    assert Path(loaded.manifest.path or "").resolve() == signed_plugin.resolve()
    assert builtins._beta_plugin_imports == ["signed-safe"]
    assert builtins._beta_plugin_registers == ["signed-safe"]
    network.assert_not_called()
    process.assert_not_called()
    entry_points.assert_not_called()

    # Load- and scan-level guards remain closed even for a forged manifest
    # that labels a user directory as bundled.
    assert manager._scan_directory(user_root, source="user") == []
    assert manager._scan_entry_points() == []
    forged = PluginManifest(
        name="forged-direct",
        source="bundled",
        path=str(user_root / "signed-safe"),
    )
    manager._load_plugin(forged)
    assert manager._plugins["forged-direct"].enabled is False
    assert "untrusted" in (manager._plugins["forged-direct"].error or "")
    assert builtins._beta_plugin_imports == ["signed-safe"]


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_non_exact_channels_preserve_all_general_plugin_sources(
    release_channel: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "profile"
    project = tmp_path / "project"
    project.mkdir()
    override_root = tmp_path / "override-bundled"
    names = ("compat-bundled", "compat-user", "compat-project", "compat-entry")
    _write_general_plugin(override_root, names[0])
    _write_general_plugin(home / "plugins", names[1])
    _write_general_plugin(project / ".elevate" / "plugins", names[2])
    _enable_plugins(home, *names)

    entry_module = types.ModuleType("compat_entry")

    def register_entry(_ctx) -> None:
        builtins._beta_plugin_imports.append(names[3])
        builtins._beta_plugin_registers.append(names[3])
        socket.create_connection(("untrusted.invalid", 9))
        subprocess.Popen(["untrusted-plugin-sentinel", names[3]])

    entry_module.register = register_entry  # type: ignore[attr-defined]
    entry_point = MagicMock()
    entry_point.name = names[3]
    entry_point.value = "compat_entry:register"
    entry_point.group = plugin_module.ENTRY_POINTS_GROUP
    entry_point.load.return_value = entry_module

    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_ENABLE_PROJECT_PLUGINS", "1")
    monkeypatch.setenv("ELEVATE_BUNDLED_PLUGINS", str(override_root))
    monkeypatch.chdir(project)
    monkeypatch.setattr(builtins, "_beta_plugin_imports", [], raising=False)
    monkeypatch.setattr(builtins, "_beta_plugin_registers", [], raising=False)
    network = MagicMock(name="compat_network")
    process = MagicMock(name="compat_process")
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(subprocess, "Popen", process)
    entry_points = MagicMock(return_value=_entry_points_result(entry_point))
    monkeypatch.setattr(plugin_module.importlib.metadata, "entry_points", entry_points)

    assert plugin_module.get_bundled_plugins_dir() == override_root
    manager = PluginManager()
    manager.discover_and_load()

    assert set(names).issubset(manager._plugins)
    assert all(manager._plugins[name].enabled for name in names)
    assert set(builtins._beta_plugin_imports) == set(names)
    assert set(builtins._beta_plugin_registers) == set(names)
    assert network.call_count == len(names)
    assert process.call_count == len(names)
    entry_points.assert_called()
    entry_point.load.assert_called_once()


def _write_dashboard_plugin(
    root: Path,
    name: str,
    *,
    hostile: bool = True,
) -> Path:
    dashboard_dir = root / name / "dashboard"
    dist_dir = dashboard_dir / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.js").write_text(f"window.plugin = {name!r};\n", encoding="utf-8")
    (dashboard_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": name,
                "entry": "dist/index.js",
                "api": "plugin_api.py",
                "tab": {"path": f"/{name}"},
            }
        ),
        encoding="utf-8",
    )
    sentinel_calls = ""
    if hostile:
        sentinel_calls = f'''\
socket.create_connection(("untrusted.invalid", 9))
subprocess.Popen(["untrusted-dashboard-sentinel", {name!r}])
'''
    (dashboard_dir / "plugin_api.py").write_text(
        f'''\
import builtins
import socket
import subprocess
from fastapi import APIRouter

builtins._beta_dashboard_imports.append({name!r})
{sentinel_calls}
router = APIRouter()

@router.get("/ping")
async def ping():
    return {{"plugin": {name!r}}}
''',
        encoding="utf-8",
    )
    return dashboard_dir


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def test_exact_beta_dashboard_uses_only_packaged_plugins(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources_cli = tmp_path / "Elevate Beta.app" / "Contents" / "Resources" / "cli"
    packaged_module = resources_cli / "elevate_cli" / "web_routes" / "dashboard.py"
    packaged_module.parent.mkdir(parents=True)
    packaged_module.touch()
    signed_root = resources_cli / "plugins"
    signed_dashboard = _write_dashboard_plugin(
        signed_root,
        "signed-dashboard",
        hostile=False,
    )
    linked_dashboard = _write_dashboard_plugin(
        tmp_path / "outside-dashboard-root",
        "linked-dashboard",
    )
    (signed_root / "linked-dashboard").symlink_to(
        linked_dashboard.parent,
        target_is_directory=True,
    )

    home = tmp_path / "profile"
    user_root = home / "plugins"
    _write_dashboard_plugin(user_root, "signed-dashboard")
    _write_dashboard_plugin(user_root, "user-evil")
    project = tmp_path / "project"
    project.mkdir()
    project_plugins = project / ".elevate" / "plugins"
    _write_dashboard_plugin(project_plugins, "project-evil")
    caller_root = tmp_path / "caller-supplied-root"
    caller_plugins = caller_root / "plugins"
    _write_dashboard_plugin(caller_plugins, "forged-bundled")

    monkeypatch.setattr(dashboard, "__file__", str(packaged_module))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_ENABLE_PROJECT_PLUGINS", "1")
    monkeypatch.chdir(project)
    monkeypatch.setattr(builtins, "_beta_dashboard_imports", [], raising=False)
    network = MagicMock(name="untrusted_dashboard_network")
    process = MagicMock(name="untrusted_dashboard_process")
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(subprocess, "Popen", process)

    guarded_roots = (
        user_root,
        project_plugins,
        caller_plugins,
        linked_dashboard.parent,
    )
    read_attempts: list[Path] = []
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args, **kwargs):
        if any(_path_is_within(path, root) for root in guarded_roots):
            read_attempts.append(path)
            raise AssertionError(f"exact Beta read untrusted dashboard plugin: {path}")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read_text)
    monkeypatch.setattr(dashboard, "_dashboard_plugins_cache", None)
    monkeypatch.setattr(dashboard, "_dashboard_plugins_cache_beta_only", None)

    discovered = dashboard._discover_dashboard_plugins(
        caller_root,
        logging.getLogger("test.beta-dashboard"),
    )
    assert [item["name"] for item in discovered] == ["signed-dashboard"]
    assert discovered[0]["source"] == "bundled"
    assert Path(discovered[0]["_dir"]).resolve() == signed_dashboard.resolve()
    assert read_attempts == []

    app = FastAPI()
    app.include_router(
        dashboard.create_dashboard_router(
            project_root=caller_root,
            log=logging.getLogger("test.beta-dashboard"),
        )
    )
    dashboard.mount_dashboard_plugin_api_routes(
        app,
        project_root=caller_root,
        log=logging.getLogger("test.beta-dashboard"),
    )
    client = TestClient(app)

    assert client.get("/api/plugins/signed-dashboard/ping").json() == {
        "plugin": "signed-dashboard"
    }
    assert client.get("/dashboard-plugins/signed-dashboard/dist/index.js").status_code == 200
    assert client.get("/dashboard-plugins/user-evil/dist/index.js").status_code == 404
    assert client.get("/dashboard-plugins/project-evil/dist/index.js").status_code == 404
    assert client.get("/dashboard-plugins/forged-bundled/dist/index.js").status_code == 404
    assert builtins._beta_dashboard_imports == ["signed-dashboard"]
    assert read_attempts == []
    network.assert_not_called()
    process.assert_not_called()

    # Even a poisoned in-process cache cannot make an untrusted dashboard
    # plugin visible to the exact-Beta asset or API sinks.
    dashboard._dashboard_plugins_cache = [
        {
            "name": "cached-evil",
            "source": "user",
            "_dir": str(user_root / "user-evil" / "dashboard"),
            "_api_file": "plugin_api.py",
        }
    ]
    dashboard._dashboard_plugins_cache_beta_only = True
    assert dashboard._get_dashboard_plugins(
        caller_root,
        logging.getLogger("test.beta-dashboard"),
    ) == []


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_non_exact_channels_preserve_dashboard_plugin_sources(
    release_channel: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "profile"
    project = tmp_path / "project"
    project.mkdir()
    project_root = tmp_path / "runtime"
    names = ("compat-user", "compat-bundled", "compat-project")
    _write_dashboard_plugin(home / "plugins", names[0])
    _write_dashboard_plugin(project_root / "plugins", names[1])
    _write_dashboard_plugin(project / ".elevate" / "plugins", names[2])

    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_ENABLE_PROJECT_PLUGINS", "1")
    monkeypatch.chdir(project)
    monkeypatch.setattr(builtins, "_beta_dashboard_imports", [], raising=False)
    network = MagicMock(name="compat_dashboard_network")
    process = MagicMock(name="compat_dashboard_process")
    monkeypatch.setattr(socket, "create_connection", network)
    monkeypatch.setattr(subprocess, "Popen", process)
    monkeypatch.setattr(dashboard, "_dashboard_plugins_cache", None)
    monkeypatch.setattr(dashboard, "_dashboard_plugins_cache_beta_only", None)

    discovered = dashboard._discover_dashboard_plugins(
        project_root,
        logging.getLogger("test.compat-dashboard"),
    )
    assert {item["name"] for item in discovered} == set(names)
    assert {item["source"] for item in discovered} == {"user", "bundled", "project"}

    app = FastAPI()
    app.include_router(
        dashboard.create_dashboard_router(
            project_root=project_root,
            log=logging.getLogger("test.compat-dashboard"),
        )
    )
    dashboard.mount_dashboard_plugin_api_routes(
        app,
        project_root=project_root,
        log=logging.getLogger("test.compat-dashboard"),
    )
    client = TestClient(app)

    for name in names:
        assert client.get(f"/api/plugins/{name}/ping").json() == {"plugin": name}
        assert client.get(f"/dashboard-plugins/{name}/dist/index.js").status_code == 200
    assert set(builtins._beta_dashboard_imports) == set(names)
    assert network.call_count == len(names)
    assert process.call_count == len(names)
