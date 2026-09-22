from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_update_template_allows_existing_release_directory() -> None:
    template = (PROJECT_ROOT / "release" / "deploy-update.template.sh").read_text(
        encoding="utf-8"
    )

    assert "发布或备份目录已存在，拒绝覆盖" not in template
    assert "RELEASE_DIR" in template
    assert "BACKUP_DIR" in template
    assert ".previous-" in template
    assert 'mv -- "$path" "$archived"' in template


def test_initial_deploy_allows_existing_release_directory() -> None:
    script = (PROJECT_ROOT / "release" / "deploy-nicokara-from-data.sh").read_text(
        encoding="utf-8"
    )

    assert "发布目录非空，拒绝覆盖" not in script
    assert "RELEASE_DIR" in script
    assert ".previous-" in script
    assert 'mv -- "$RELEASE_DIR" "$EXISTING_RELEASE_BACKUP"' in script
