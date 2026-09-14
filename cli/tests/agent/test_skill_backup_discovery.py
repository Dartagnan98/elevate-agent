from agent.skill_utils import iter_skill_index_files, is_excluded_skill_path

def test_backup_copies_cannot_shadow_active_skill(tmp_path):
    for folder in [".bundled-base/admin-result-writer", "real-estate-admin/admin-result-writer", "real-estate-admin/admin-result-writer.stale-bak", "node_modules/example"]:
        path = tmp_path / folder / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: admin-result-writer\ndescription: Test\n---\n")
    assert list(iter_skill_index_files(tmp_path, "SKILL.md")) == [tmp_path / "real-estate-admin/admin-result-writer/SKILL.md"]
    assert is_excluded_skill_path(tmp_path / ".bundled-base/admin-result-writer/SKILL.md")
    assert is_excluded_skill_path(tmp_path / "real-estate-admin/admin-result-writer.stale-bak/SKILL.md")

def test_active_skill_can_symlink_to_installer_copy(tmp_path):
    saved = tmp_path / ".bundled-base/example"
    saved.mkdir(parents=True)
    (saved / "SKILL.md").write_text("active through link")
    (tmp_path / "example").symlink_to(saved, target_is_directory=True)
    assert list(iter_skill_index_files(tmp_path, "SKILL.md")) == [tmp_path / "example/SKILL.md"]
