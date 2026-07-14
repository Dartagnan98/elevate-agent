"""Exact-Realtor-Beta shell-hook and skill trust-boundary regressions."""

from __future__ import annotations

import builtins
import json
import subprocess
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

import elevate_constants
from agent import prompt_builder, shell_hooks, skill_commands, skill_preprocessing
from agent import skill_utils
from tools import credential_files, skill_manager_tool, skills_tool


@pytest.fixture(autouse=True)
def _reset_shell_and_skill_registries(monkeypatch: pytest.MonkeyPatch):
    shell_hooks.reset_for_tests()
    monkeypatch.setattr(skill_commands, "_skill_commands", {})
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)
    yield
    shell_hooks.reset_for_tests()
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)


def _hook_config(command: str = "untrusted-hook --run") -> dict:
    return {
        "hooks_auto_accept": True,
        "hooks": {
            "pre_tool_call": [
                {
                    "command": command,
                    "matcher": "terminal",
                    "timeout": 5,
                }
            ]
        },
    }


def test_exact_beta_never_imports_registers_or_runs_config_shell_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    process = MagicMock(side_effect=AssertionError("exact Beta spawned a hook"))
    monkeypatch.setattr(shell_hooks.subprocess, "run", process)
    monkeypatch.setattr(
        shell_hooks,
        "_is_allowlisted",
        MagicMock(side_effect=AssertionError("exact Beta read the hook allowlist")),
    )
    monkeypatch.setattr(
        shell_hooks,
        "_prompt_and_record",
        MagicMock(side_effect=AssertionError("exact Beta approved a hook")),
    )

    imported_plugins: list[str] = []
    original_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "elevate_cli.plugins":
            imported_plugins.append(name)
            raise AssertionError("exact Beta imported PluginManager for a shell hook")
        return original_import(name, globals, locals, fromlist, level)

    with pytest.MonkeyPatch.context() as import_patch:
        import_patch.setattr(builtins, "__import__", guarded_import)
        assert shell_hooks.register_from_config(_hook_config(), accept_hooks=True) == []

    assert imported_plugins == []
    assert shell_hooks._registered == set()

    spec = shell_hooks.ShellHookSpec(
        event="pre_tool_call",
        command="untrusted-hook --run",
        matcher="terminal",
    )
    direct = shell_hooks._spawn(spec, "{}")
    assert direct["returncode"] is None
    assert "disabled in Realtor Beta" in str(direct["error"])
    callback = shell_hooks._make_callback(spec)
    assert callback(tool_name="terminal", args={}) is None
    process.assert_not_called()


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_non_exact_channels_preserve_shell_hook_registration_and_execution(
    release_channel: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)

    manager = types.SimpleNamespace(_hooks={})
    import elevate_cli.plugins as plugin_module

    monkeypatch.setattr(plugin_module, "get_plugin_manager", lambda: manager)
    monkeypatch.setattr(shell_hooks, "_is_allowlisted", lambda *_args: True)
    completed = subprocess.CompletedProcess(
        ["untrusted-hook", "--run"],
        0,
        stdout='{"action":"block","message":"compat"}',
        stderr="",
    )
    process = MagicMock(return_value=completed)
    monkeypatch.setattr(shell_hooks.subprocess, "run", process)

    registered = shell_hooks.register_from_config(_hook_config())
    assert len(registered) == 1
    callbacks = manager._hooks["pre_tool_call"]
    assert len(callbacks) == 1
    assert callbacks[0](tool_name="terminal", args={"command": "pwd"}) == {
        "action": "block",
        "message": "compat",
    }
    process.assert_called_once()
    assert process.call_args.args[0] == ["untrusted-hook", "--run"]


def test_exact_beta_leaves_inline_shell_literal_across_both_preprocessors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    process = MagicMock(side_effect=AssertionError("exact Beta ran inline shell"))
    monkeypatch.setattr(subprocess, "run", process)
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    content = "Root=${ELEVATE_SKILL_DIR}; value=!`untrusted-inline --run`"
    cfg = {"template_vars": True, "inline_shell": True, "inline_shell_timeout": 5}

    rendered = skill_preprocessing.preprocess_skill_content(
        content,
        skill_dir,
        skills_cfg=cfg,
    )
    assert rendered == f"Root={skill_dir}; value=!`untrusted-inline --run`"
    assert skill_preprocessing.expand_inline_shell(content, skill_dir, 5) == content
    assert skill_preprocessing.run_inline_shell("untrusted-inline --run", skill_dir, 5) == (
        "[inline-shell disabled in Realtor Beta]"
    )

    monkeypatch.setattr(skill_commands, "_load_skills_config", lambda: cfg)
    slash_message = skill_commands._build_skill_message(
        {"content": content},
        skill_dir,
        "[activation]",
    )
    assert f"Root={skill_dir}; value=!`untrusted-inline --run`" in slash_message
    assert skill_commands._expand_inline_shell(content, skill_dir, 5) == content
    assert skill_commands._run_inline_shell("untrusted-inline --run", skill_dir, 5) == (
        "[inline-shell disabled in Realtor Beta]"
    )
    process.assert_not_called()


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_non_exact_channels_preserve_both_inline_shell_preprocessors(
    release_channel: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    cfg = {"template_vars": True, "inline_shell": True, "inline_shell_timeout": 5}
    completed = subprocess.CompletedProcess(
        ["bash", "-c", "compat-inline"],
        0,
        stdout="EXECUTED\n",
        stderr="",
    )
    process = MagicMock(return_value=completed)
    monkeypatch.setattr(subprocess, "run", process)

    rendered = skill_preprocessing.preprocess_skill_content(
        "value=!`compat-inline`",
        tmp_path,
        skills_cfg=cfg,
    )
    assert rendered == "value=EXECUTED"

    monkeypatch.setattr(skill_commands, "_load_skills_config", lambda: cfg)
    slash_message = skill_commands._build_skill_message(
        {"content": "value=!`compat-inline`"},
        tmp_path,
        "[activation]",
    )
    assert "value=EXECUTED" in slash_message
    assert process.call_count == 2


def _write_skill(root: Path, relative: str, *, name: str | None = None) -> Path:
    skill_dir = root / relative
    skill_dir.mkdir(parents=True, exist_ok=True)
    declared_name = name or skill_dir.name
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {declared_name}\n"
        f"description: Signed test skill {declared_name}\n"
        "---\n\n"
        f"# {declared_name}\n\n"
        "Signed instructions. Inline sentinel: !`untrusted-skill-shell --run`\n",
        encoding="utf-8",
    )
    return skill_dir


_ADMIN_PACK_SKILLS = (
    "real-estate-admin/admin-agent",
    "real-estate-admin/admin-result-writer",
    "real-estate-admin/closing-admin",
    "real-estate-admin/cma-generator",
    "real-estate-admin/deal-matcher",
    "real-estate-admin/digisign",
    "real-estate-admin/gmail-doc-router",
    "real-estate-admin/offer-review",
    "real-estate-admin/signing-package",
    "real-estate-admin/skyslope-sync",
    "real-estate-admin/subject-removal",
    "real-estate-admin/webforms",
)


def test_exact_beta_runtime_indexes_only_packaged_signed_skills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources_cli = tmp_path / "Elevate Beta.app" / "Contents" / "Resources" / "cli"
    constants_file = resources_cli / "elevate_constants.py"
    constants_file.parent.mkdir(parents=True)
    constants_file.touch()
    signed_root = resources_cli / "skills"
    for relative in (*_ADMIN_PACK_SKILLS, "real-estate/surface-heartbeat"):
        _write_skill(signed_root, relative)

    outside_link = _write_skill(
        tmp_path / "outside-signed-skills",
        "linked-evil",
        name="linked-evil",
    )
    (signed_root / "linked-evil").symlink_to(outside_link, target_is_directory=True)

    home = tmp_path / "profile"
    _write_skill(home / "skills", "admin-agent", name="profile-evil")
    _write_skill(home / "cloud-skills", "cloud-evil")
    external = tmp_path / "external-skills"
    _write_skill(external, "external-evil")
    project = tmp_path / "project"
    project.mkdir()
    project_skills = project / ".elevate" / "skills"
    _write_skill(project_skills, "project-evil")
    override = tmp_path / "override-bundled"
    _write_skill(override, "override-evil")
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {"skills": {"external_dirs": [str(external), str(project_skills)]}}
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(elevate_constants, "__file__", str(constants_file))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_BUNDLED_SKILLS", str(override))
    monkeypatch.setenv("ELEVATE_EXTRA_SKILLS_PATH", str(external))
    monkeypatch.setenv("ELEVATE_EXTRA_SKILLS_DIRS", str(project_skills))
    monkeypatch.chdir(project)
    monkeypatch.setattr(skills_tool, "ELEVATE_HOME", home)
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", signed_root)
    monkeypatch.setattr(skill_manager_tool, "SKILLS_DIR", home / "skills")
    process = MagicMock(side_effect=AssertionError("exact Beta ran skill shell"))
    monkeypatch.setattr(subprocess, "run", process)

    assert elevate_constants.get_runtime_skills_dir() == signed_root
    assert elevate_constants.get_bundled_skills_dir(override) == signed_root
    assert skill_utils.get_external_skills_dirs() == []
    assert skill_utils.get_all_skills_dirs() == [signed_root]

    indexed = list(skill_utils.iter_skill_index_files(signed_root, "SKILL.md"))
    assert len(indexed) == len(_ADMIN_PACK_SKILLS) + 1
    assert all("linked-evil" not in str(path) for path in indexed)

    available = skills_tool._find_all_skills()
    available_names = {item["name"] for item in available}
    assert "admin-agent" in available_names
    assert "surface-heartbeat" in available_names
    assert not {
        "profile-evil",
        "cloud-evil",
        "external-evil",
        "project-evil",
        "override-evil",
        "linked-evil",
    } & available_names

    viewed = json.loads(skills_tool.skill_view("real-estate-admin/admin-agent"))
    assert viewed["success"] is True
    assert viewed["name"] == "admin-agent"
    assert "!`untrusted-skill-shell --run`" in viewed["content"]

    prompt = prompt_builder.build_skills_system_prompt()
    assert "admin-agent" in prompt
    assert "surface-heartbeat" in prompt
    assert "profile-evil" not in prompt
    assert "external-evil" not in prompt

    commands = skill_commands.scan_skill_commands()
    assert "/admin-agent" in commands
    assert "/surface-heartbeat" in commands
    assert "/profile-evil" not in commands
    assert "/external-evil" not in commands

    mounts = credential_files.get_skills_directory_mount()
    assert len(mounts) == 1
    assert mounts[0]["container_path"] == "/root/.elevate/skills"
    mounted_root = Path(mounts[0]["host_path"])
    assert (mounted_root / "real-estate-admin" / "admin-agent" / "SKILL.md").is_file()
    assert not (mounted_root / "linked-evil").exists()
    assert home / "skills" != mounted_root
    uploaded_paths = {
        item["host_path"] for item in credential_files.iter_skills_files()
    }
    assert str(signed_root / "real-estate-admin" / "admin-agent" / "SKILL.md") in uploaded_paths
    assert not any(str(home / "skills") in item for item in uploaded_paths)

    signed_admin = signed_root / "real-estate-admin" / "admin-agent"
    original_admin = (signed_admin / "SKILL.md").read_text(encoding="utf-8")
    mutation_calls = (
        lambda: skill_manager_tool._edit_skill("admin-agent", original_admin),
        lambda: skill_manager_tool._patch_skill(
            "admin-agent", "Signed instructions.", "Changed instructions."
        ),
        lambda: skill_manager_tool._delete_skill("admin-agent"),
        lambda: skill_manager_tool._write_file(
            "admin-agent", "references/evil.md", "changed"
        ),
        lambda: skill_manager_tool._remove_file(
            "admin-agent", "references/missing.md"
        ),
    )
    for mutation in mutation_calls:
        result = mutation()
        assert result["success"] is False
        assert "read-only" in result["error"]
    assert (signed_admin / "SKILL.md").read_text(encoding="utf-8") == original_admin
    assert not (signed_admin / "references" / "evil.md").exists()
    process.assert_not_called()


def test_signed_app_payload_contains_current_realtor_admin_pack_skills() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    signed_skills = repo_root / "cli" / "skills"
    assert signed_skills == elevate_constants.get_code_bundled_skills_dir()

    from elevate_cli.agent_hub import _AGENT_EFFECTIVE_SKILL_ALIASES

    admin_aliases = tuple(_AGENT_EFFECTIVE_SKILL_ALIASES["admin"].values())
    assert set(admin_aliases) == set(_ADMIN_PACK_SKILLS)
    missing = [
        relative
        for relative in admin_aliases
        if not (signed_skills / relative / "SKILL.md").is_file()
    ]
    assert missing == []
    assert (signed_skills / "real-estate" / "surface-heartbeat" / "SKILL.md").is_file()
    assert (signed_skills / "outreach-lanes" / "SKILL.md").is_file()
    assert len(list((signed_skills / "real-estate-admin").glob("*/SKILL.md"))) >= 60

    package_json = json.loads((repo_root / "desktop" / "package.json").read_text())
    cli_resource = next(
        item
        for item in package_json["build"]["extraResources"]
        if item.get("from") == "../cli" and item.get("to") == "cli"
    )
    assert not any(
        str(pattern).startswith("!skills")
        for pattern in cli_resource.get("filter", [])
    )


@pytest.mark.parametrize("release_channel", [None, "Beta"])
def test_non_exact_channels_preserve_profile_project_and_external_skill_roots(
    release_channel: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "profile"
    local = home / "skills"
    local.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    configured_project = tmp_path / "configured-project" / ".elevate" / "skills"
    configured_project.mkdir(parents=True)
    unconfigured_project = tmp_path / "unconfigured-project"
    (unconfigured_project / ".elevate" / "skills").mkdir(parents=True)
    env_extra = tmp_path / "env-extra"
    env_extra.mkdir()
    cloud = home / "cloud-skills"
    cloud.mkdir()
    override = tmp_path / "override-bundled"
    override.mkdir()
    (home / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "skills": {
                    "external_dirs": [str(external), str(configured_project)]
                }
            }
        ),
        encoding="utf-8",
    )

    if release_channel is None:
        monkeypatch.delenv("ELEVATE_RELEASE_CHANNEL", raising=False)
    else:
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", release_channel)
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_EXTRA_SKILLS_PATH", str(env_extra))
    monkeypatch.setenv("ELEVATE_BUNDLED_SKILLS", str(override))
    monkeypatch.chdir(unconfigured_project)

    assert elevate_constants.get_runtime_skills_dir() == local
    assert elevate_constants.get_bundled_skills_dir() == override
    roots = skill_utils.get_all_skills_dirs()
    assert roots[0] == local
    assert external.resolve() in roots
    assert configured_project.resolve() in roots
    assert env_extra.resolve() in roots
    assert cloud.resolve() in roots
    assert (unconfigured_project / ".elevate" / "skills").resolve() not in roots
