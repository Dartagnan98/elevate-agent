"""Tests for prompt-hidden skills: hidden from system prompt, still loadable."""

import json


def _write_skill(root, folder, name, description, extra_frontmatter=""):
    skill_dir = root / folder
    skill_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"{extra_frontmatter}"
        "---\n\n"
        f"# {name}\n\n"
        "Use this skill.\n"
    )
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    return skill_dir


def test_prompt_hidden_config_hides_from_system_prompt_but_not_skill_view(
    tmp_path, monkeypatch
):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "skills:\n  prompt_hidden:\n    - phase-skill\n",
        encoding="utf-8",
    )
    _write_skill(skills_dir, "router", "router-skill", "Router skill")
    _write_skill(skills_dir, "phase-skill", "phase-skill", "Phase skill")

    monkeypatch.setenv("ELEVATE_HOME", str(home))

    from agent.prompt_builder import (
        build_skills_system_prompt,
        clear_skills_system_prompt_cache,
    )
    import tools.skills_tool as skills_tool_module

    monkeypatch.setattr(skills_tool_module, "ELEVATE_HOME", home)
    monkeypatch.setattr(skills_tool_module, "SKILLS_DIR", skills_dir)

    clear_skills_system_prompt_cache(clear_snapshot=True)
    prompt = build_skills_system_prompt()

    assert "router-skill" in prompt
    assert "phase-skill" not in prompt

    loaded = json.loads(skills_tool_module.skill_view("phase-skill"))
    assert loaded["success"] is True
    assert "# phase-skill" in loaded["content"]


def test_agent_prompt_hidden_only_affects_matching_agent(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text(
        "skills:\n"
        "  agent_prompt_hidden:\n"
        "    executive-assistant:\n"
        "      - phase-skill\n",
        encoding="utf-8",
    )
    _write_skill(skills_dir, "phase-skill", "phase-skill", "Phase skill")

    monkeypatch.setenv("ELEVATE_HOME", str(home))

    from agent.prompt_builder import (
        build_skills_system_prompt,
        clear_skills_system_prompt_cache,
    )

    clear_skills_system_prompt_cache(clear_snapshot=True)
    monkeypatch.setenv("ELEVATE_AGENT_ID", "admin")
    admin_prompt = build_skills_system_prompt()
    assert "phase-skill" in admin_prompt

    clear_skills_system_prompt_cache(clear_snapshot=True)
    monkeypatch.setenv("ELEVATE_AGENT_ID", "executive-assistant")
    executive_prompt = build_skills_system_prompt()
    assert "phase-skill" not in executive_prompt


def test_frontmatter_prompt_hidden_hides_from_system_prompt(tmp_path, monkeypatch):
    home = tmp_path / ".elevate"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    (home / "config.yaml").write_text("skills:\n  external_dirs: []\n", encoding="utf-8")
    _write_skill(
        skills_dir,
        "phase",
        "phase-skill",
        "Phase skill",
        "metadata:\n  elevate:\n    prompt_hidden: true\n",
    )

    monkeypatch.setenv("ELEVATE_HOME", str(home))

    from agent.prompt_builder import (
        build_skills_system_prompt,
        clear_skills_system_prompt_cache,
    )

    clear_skills_system_prompt_cache(clear_snapshot=True)
    prompt = build_skills_system_prompt()
    assert "phase-skill" not in prompt
