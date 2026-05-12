"""Tests for local access profiles and premium skill locking."""

import json
from unittest.mock import patch


def _write_skill(root, folder, name, description, extra_frontmatter=""):
    skill_dir = root / folder
    skill_dir.mkdir(parents=True)
    frontmatter = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra_frontmatter}"
        "---\n\n"
        f"# {name}\n\n"
        "Use this skill.\n"
    )
    (skill_dir / "SKILL.md").write_text(frontmatter, encoding="utf-8")
    return skill_dir


def test_default_access_locks_team_pack(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    monkeypatch.delenv("ELEVATE_DEV_UNLOCK_REAL_ESTATE_DASHBOARDS", raising=False)

    from elevate_cli.access import (
        ENTITLEMENT_CORE,
        ENTITLEMENT_EXP,
        ENTITLEMENT_TEAM_PACK,
        is_entitlement_active,
        load_access_config,
    )

    access = load_access_config({"access": {"profile": "standalone"}})
    assert is_entitlement_active(ENTITLEMENT_CORE, access) is True
    assert is_entitlement_active(ENTITLEMENT_EXP, access) is False
    assert is_entitlement_active(ENTITLEMENT_TEAM_PACK, access) is False


def test_dashboard_access_keeps_paid_packs_locked_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    monkeypatch.delenv("ELEVATE_DEV_UNLOCK_REAL_ESTATE_DASHBOARDS", raising=False)

    from elevate_cli.access import dashboard_access_status, load_access_config

    access = load_access_config({"access": {"profile": "standalone"}})
    status = dashboard_access_status(access)

    assert status["devOverride"] is False
    assert status["mode"] == "entitlement"
    assert status["packs"] == {
        "realEstateSales": False,
        "realEstateMarketing": False,
        "realEstateAdmin": False,
        "realEstateCma": False,
        "realEstateAny": False,
    }


def test_dashboard_access_dev_override_unlocks_local_dashboards(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))
    monkeypatch.setenv("ELEVATE_DEV_UNLOCK_REAL_ESTATE_DASHBOARDS", "1")

    from elevate_cli.access import dashboard_access_status, load_access_config

    access = load_access_config({"access": {"profile": "standalone"}})
    status = dashboard_access_status(access)

    assert status["devOverride"] is True
    assert status["mode"] == "development"
    assert status["packs"] == {
        "realEstateSales": True,
        "realEstateMarketing": True,
        "realEstateAdmin": True,
        "realEstateCma": True,
        "realEstateAny": True,
    }


def test_team_profile_locks_team_pack_when_affiliation_leaves(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))

    from elevate_cli.access import (
        ENTITLEMENT_TEAM_PACK,
        default_access_config,
        is_entitlement_active,
    )

    access = default_access_config("team_pack")
    assert is_entitlement_active(ENTITLEMENT_TEAM_PACK, access) is True
    access["affiliation"]["status"] = "left_team"
    assert is_entitlement_active(ENTITLEMENT_TEAM_PACK, access) is False


def test_profile_promotes_default_locks_but_respects_manual_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("ELEVATE_HOME", str(tmp_path))

    from elevate_cli.access import (
        ENTITLEMENT_TEAM_PACK,
        is_entitlement_active,
        load_access_config,
    )

    raw = {
        "profile": "team_pack",
        "entitlements": {
            "real_estate_team_pack": {
                "status": "locked",
                "requires_active_affiliation": True,
            }
        },
    }
    promoted = load_access_config({"access": raw})
    assert is_entitlement_active(ENTITLEMENT_TEAM_PACK, promoted) is True

    raw["entitlements"]["real_estate_team_pack"]["manual_lock"] = True
    locked = load_access_config({"access": raw})
    assert is_entitlement_active(ENTITLEMENT_TEAM_PACK, locked) is False


def test_skill_list_and_view_hide_locked_pack(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text("access:\n  profile: standalone\n", encoding="utf-8")

    _write_skill(skills_dir, "free-skill", "free-skill", "Free skill")
    _write_skill(
        skills_dir,
        "team-skill",
        "team-skill",
        "Team skill",
        "access:\n  entitlement: real_estate_team_pack\n",
    )

    monkeypatch.setenv("ELEVATE_HOME", str(home))
    with patch("tools.skills_tool.SKILLS_DIR", skills_dir):
        from tools.skills_tool import _find_all_skills, skill_view

        names = [skill["name"] for skill in _find_all_skills()]
        assert "free-skill" in names
        assert "team-skill" not in names

        locked = json.loads(skill_view("team-skill"))
        assert locked["success"] is False
        assert locked["readiness_status"] == "locked"
        assert locked["access"]["locked_entitlements"] == ["real_estate_team_pack"]


def test_skill_view_allows_team_pack_for_active_team_profile(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "access:\n  profile: team_pack\n",
        encoding="utf-8",
    )
    _write_skill(
        skills_dir,
        "team-skill",
        "team-skill",
        "Team skill",
        "access:\n  entitlement: real_estate_team_pack\n",
    )

    monkeypatch.setenv("ELEVATE_HOME", str(home))
    with patch("tools.skills_tool.SKILLS_DIR", skills_dir):
        from tools.skills_tool import _find_all_skills, skill_view

        names = [skill["name"] for skill in _find_all_skills()]
        assert "team-skill" in names

        loaded = json.loads(skill_view("team-skill"))
        assert loaded["success"] is True
        assert "Use this skill" in loaded["content"]


def test_skills_prompt_excludes_locked_team_pack(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text("access:\n  profile: standalone\n", encoding="utf-8")
    _write_skill(skills_dir, "free-skill", "free-skill", "Free skill")
    _write_skill(
        skills_dir,
        "team-skill",
        "team-skill",
        "Team skill",
        "access:\n  entitlement: real_estate_team_pack\n",
    )

    monkeypatch.setenv("ELEVATE_HOME", str(home))
    from agent.prompt_builder import (
        build_skills_system_prompt,
        clear_skills_system_prompt_cache,
    )

    clear_skills_system_prompt_cache(clear_snapshot=True)
    prompt = build_skills_system_prompt()
    assert "free-skill" in prompt
    assert "team-skill" not in prompt


def test_env_extra_skills_path_is_scanned(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    local_skills = home / "skills"
    local_skills.mkdir(parents=True)
    (home / "config.yaml").write_text("skills:\n  external_dirs: []\n", encoding="utf-8")
    external = tmp_path / "mounted-premium"
    _write_skill(external, "mounted", "mounted-skill", "Mounted skill")

    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setenv("ELEVATE_EXTRA_SKILLS_PATH", str(external))

    from agent.skill_utils import get_external_skills_dirs

    assert external.resolve() in get_external_skills_dirs()
