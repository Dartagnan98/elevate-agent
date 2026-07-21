"""Exact-Realtor-Beta entitled-root skill surface regressions.

``is_trusted_beta_bundled_skill_path`` proves a skill came from the signed app
bundle. That is NOT the customer-facing property: the signed bundle also ships
the whole engineering catalog (mlops, devops, github, software-development, …)
plus, historically, an LLM-jailbreak skill. Only the roots in
``REALTOR_BETA_SKILL_ROOTS`` may be listed, routed, or loaded for a realtor.

Every test here fails if the narrower ``is_realtor_beta_surface_skill_path``
gate is reverted to the bundle-wide check at ANY of its call sites, so the
containment cannot be silently deleted. The root tuple is also the tuple hashed
into the Beta activation identity, so a change to it must be a deliberate
release event, not a refactor.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import elevate_constants
from agent import prompt_builder, skill_commands, skill_utils
from elevate_cli import beta_skill_bundle
from tools import skills_tool

# One entitled root plus every class of forbidden sibling: an engineering root,
# a prefix collision, a case collision, and a nested engineering root.
_ENTITLED = ("cma", "real-estate-admin/admin-agent", "lead-scorer")
_FORBIDDEN = (
    "red-teaming/godmode",
    "mlops/inference/obliteratus",
    "software-development/plan",
    "cma-evil/impostor",
    "cmax/impostor",
    "CMA-UPPER/impostor",
    # A skill sitting DIRECTLY under the bundle root, like the real tree's
    # dogfood / composio-inbound-puller / paid-ad-intake. These are the ones a
    # single-segment `{name}` route resolves without touching the enumerator.
    "dogfood",
)


def _write_skill(root: Path, relative: str, *, name: str | None = None) -> Path:
    skill_dir = root / relative
    skill_dir.mkdir(parents=True, exist_ok=True)
    declared = name or skill_dir.name
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {declared}\n"
        f"description: Test skill {declared}. Use when testing.\n"
        "---\n\n"
        f"# {declared}\n\nBody for {declared}.\n",
        encoding="utf-8",
    )
    return skill_dir


@pytest.fixture
def beta_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A synthetic signed bundle carrying entitled AND forbidden roots."""
    resources_cli = tmp_path / "Elevate Beta.app" / "Contents" / "Resources" / "cli"
    constants_file = resources_cli / "elevate_constants.py"
    constants_file.parent.mkdir(parents=True)
    constants_file.touch()
    signed_root = resources_cli / "skills"

    for relative in _ENTITLED:
        _write_skill(signed_root, relative)
    for relative in _FORBIDDEN:
        _write_skill(signed_root, relative)
    # A legacy flat <name>.md, reachable by skill_view strategy 3 only.
    (signed_root / "red-teaming").mkdir(parents=True, exist_ok=True)
    (signed_root / "red-teaming" / "flat-evil.md").write_text(
        "flat evil body", encoding="utf-8"
    )

    home = tmp_path / "profile"
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(yaml.safe_dump({}), encoding="utf-8")

    monkeypatch.setattr(elevate_constants, "__file__", str(constants_file))
    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "beta")
    monkeypatch.setenv("ELEVATE_HOME", str(home))
    monkeypatch.setattr(skills_tool, "ELEVATE_HOME", home)
    monkeypatch.setattr(skills_tool, "SKILLS_DIR", signed_root)
    monkeypatch.setattr(skill_commands, "_skill_commands", {})
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)
    yield signed_root
    prompt_builder.clear_skills_system_prompt_cache(clear_snapshot=True)


def test_root_tuple_is_the_same_object_as_the_hashed_bundle_identity() -> None:
    """The listing filter and the SHA-256 activation identity cannot drift."""
    assert (
        beta_skill_bundle.REALTOR_BETA_SKILL_ROOTS
        is elevate_constants.REALTOR_BETA_SKILL_ROOTS
    )
    assert elevate_constants.REALTOR_BETA_SKILL_ROOTS == (
        "real-estate",
        "real-estate-admin",
        "lead-scorer",
        "outreach-lanes",
        "social-content-engine",
        "cma",
    )


def test_surface_predicate_matches_whole_components_only(
    beta_tree: Path,
) -> None:
    surface = elevate_constants.is_realtor_beta_surface_skill_path
    trusted = elevate_constants.is_trusted_beta_bundled_skill_path

    allowed = beta_tree / "cma" / "SKILL.md"
    assert surface(allowed) is True

    # Everything below is inside the signed bundle but outside the entitled
    # roots — the two predicates MUST disagree, which is the whole point.
    for relative in (
        "red-teaming/godmode/SKILL.md",
        "mlops/inference/obliteratus/SKILL.md",
        "cma-evil/impostor/SKILL.md",
        "cmax/impostor/SKILL.md",
        "real-estate-admin/../red-teaming/godmode/SKILL.md",
    ):
        candidate = beta_tree / relative
        assert trusted(candidate) is True, relative
        assert surface(candidate) is False, relative

    # The bundle root itself is trusted but is not a skill surface path.
    assert trusted(beta_tree) is True
    assert surface(beta_tree) is False


def test_surface_predicate_refuses_symlinks_out_of_an_entitled_root(
    beta_tree: Path,
) -> None:
    surface = elevate_constants.is_realtor_beta_surface_skill_path
    (beta_tree / "cma" / "sneak").symlink_to(
        beta_tree / "red-teaming", target_is_directory=True
    )
    assert surface(beta_tree / "cma" / "sneak" / "godmode" / "SKILL.md") is False

    (beta_tree / "cma-alias").symlink_to(
        beta_tree / "red-teaming", target_is_directory=True
    )
    assert surface(beta_tree / "cma-alias" / "godmode" / "SKILL.md") is False


def test_surface_predicate_is_false_when_the_bundle_root_is_a_symlink(
    beta_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    relocated = tmp_path / "relocated-skills"
    beta_tree.rename(relocated)
    beta_tree.symlink_to(relocated, target_is_directory=True)
    assert elevate_constants.get_code_bundled_skills_dir().is_symlink()
    assert (
        elevate_constants.is_realtor_beta_surface_skill_path(beta_tree / "cma" / "SKILL.md")
        is False
    )


def test_enumeration_yields_entitled_roots_only(beta_tree: Path) -> None:
    indexed = list(skill_utils.iter_skill_index_files(beta_tree, "SKILL.md"))
    roots = {path.relative_to(beta_tree).parts[0] for path in indexed}
    assert roots <= set(elevate_constants.REALTOR_BETA_SKILL_ROOTS)
    assert len(indexed) == len(_ENTITLED)


def test_listing_and_slash_menu_expose_entitled_skills_only(beta_tree: Path) -> None:
    names = {item["name"] for item in skills_tool._find_all_skills()}
    assert names == {"cma", "admin-agent", "lead-scorer"}

    listed = json.loads(skills_tool.skills_list())
    assert {item["name"] for item in listed["skills"]} == names

    commands = skill_commands.scan_skill_commands()
    assert "/cma" in commands
    for forbidden in ("/godmode", "/obliteratus", "/plan", "/impostor"):
        assert forbidden not in commands


def test_prompt_catalog_never_advertises_a_forbidden_root(beta_tree: Path) -> None:
    prompt = prompt_builder.build_skills_system_prompt()
    assert "cma" in prompt
    for token in ("godmode", "obliteratus", "red-teaming", "mlops", "impostor"):
        assert token not in prompt, token


def test_skill_view_refuses_every_resolution_strategy(beta_tree: Path) -> None:
    served = json.loads(skills_tool.skill_view("cma"))
    assert served["success"] is True

    probes = (
        "godmode",
        "red-teaming/godmode",
        "obliteratus",
        "mlops/inference/obliteratus",
        "red-teaming:godmode",
        "local/godmode",
        "local:godmode",
        "skills/red-teaming/godmode",
        "skills:godmode",
        "cloud/godmode",
        "cloud:godmode",
        "impostor",
        "cma-evil/impostor",
        "cmax/impostor",
        "cma/../red-teaming/godmode",
        "red-teaming/flat-evil",
        str(beta_tree / "red-teaming" / "godmode"),
    )
    for probe in probes:
        result = json.loads(skills_tool.skill_view(probe))
        assert result["success"] is False, probe
        assert not result.get("content"), probe


def test_plugin_lane_refuses_a_path_outside_the_entitled_roots(
    beta_tree: Path,
) -> None:
    """``skill_view`` dispatches ``ns:bare`` to the plugin server before its
    own containment check, so the plugin server must gate independently."""
    result = json.loads(
        skills_tool._serve_plugin_skill(
            beta_tree / "red-teaming" / "godmode" / "SKILL.md",
            "red-teaming",
            "godmode",
            preprocess=False,
        )
    )
    assert result["success"] is False
    assert not result.get("content")


def test_dashboard_skill_routes_refuse_a_non_entitled_top_level_skill(
    beta_tree: Path,
) -> None:
    """``/api/skills/{name}/tree`` and ``/file`` resolve by direct path."""
    from elevate_cli.web_routes.skills import _resolve_skill_dir

    assert _resolve_skill_dir("cma") == beta_tree / "cma"
    for name in ("dogfood", "godmode", "obliteratus", "plan", "impostor"):
        assert _resolve_skill_dir(name) is None, name


def test_slash_miss_does_not_enumerate_unavailable_skills_in_beta(
    beta_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unavailable-skill hint walks optional-skills/, which ships in the
    app — in Beta it must never answer, or every typo becomes an oracle."""
    from gateway.run import _check_unavailable_skill

    assert _check_unavailable_skill("godmode") is None
    assert _check_unavailable_skill("solana") is None

    monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", "latest")
    assert elevate_constants.exact_realtor_beta_active() is False


def test_prompt_snapshot_with_a_forbidden_entry_is_rejected(
    beta_tree: Path, tmp_path: Path
) -> None:
    """The snapshot is unsigned mutable JSON under ELEVATE_HOME; a matching
    mtime/size manifest must not be enough to inject catalog entries."""
    manifest = prompt_builder._build_skills_manifest(beta_tree)
    snapshot_path = prompt_builder._skills_prompt_snapshot_path()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps(
            {
                "version": prompt_builder._SKILLS_SNAPSHOT_VERSION,
                "manifest": manifest,
                "skills": [
                    {
                        "skill_name": "godmode",
                        "frontmatter_name": "godmode",
                        "category": "red-teaming",
                        "description": "CRAFTED-SNAPSHOT-GODMODE",
                        "platforms": [],
                    }
                ],
                "category_descriptions": {},
            }
        ),
        encoding="utf-8",
    )
    assert prompt_builder._load_skills_snapshot(beta_tree) is None

    prompt_builder.clear_skills_system_prompt_cache()
    prompt = prompt_builder.build_skills_system_prompt()
    assert "CRAFTED-SNAPSHOT-GODMODE" not in prompt


def test_category_query_finds_a_core_workflow_and_never_widens_past_the_filter(
    beta_tree: Path,
) -> None:
    """Every category the model can read out of its own prompt must route."""
    listed = json.loads(skills_tool.skills_list())
    for category in listed["categories"]:
        result = json.loads(skills_tool.skills_list(category=category))
        assert result["count"] > 0, category

    # The reported bug: the prompt advertises the directory name, skills_list
    # stores the namespaced category, and the obvious guess returned nothing.
    cma = json.loads(skills_tool.skills_list(category="cma"))
    assert "cma" in {item["name"] for item in cma["skills"]}

    allowed = {item["name"] for item in skills_tool._find_all_skills()}
    for query in (
        "red-teaming",
        "mlops",
        "godmode",
        "software-development",
        "cma-evil",
        "_",
        "a",
        "-",
        "..",
        "real-estate-admin-and-red-teaming",
    ):
        result = json.loads(skills_tool.skills_list(category=query))
        assert {item["name"] for item in result["skills"]} <= allowed, query

    miss = json.loads(skills_tool.skills_list(category="no-such-category"))
    assert miss["count"] == 0
    assert miss["message"]
    assert miss["available_categories"] == listed["categories"]


def test_other_channels_keep_the_whole_library(
    beta_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filter is exact-``beta`` only — Stable must be untouched."""
    for channel in ("latest", "stable", "Beta", "BETA", ""):
        monkeypatch.setenv("ELEVATE_RELEASE_CHANNEL", channel)
        indexed = list(skill_utils.iter_skill_index_files(beta_tree, "SKILL.md"))
        assert len(indexed) == len(_ENTITLED) + len(_FORBIDDEN), channel
