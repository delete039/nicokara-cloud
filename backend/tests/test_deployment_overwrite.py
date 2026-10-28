from pathlib import Path
import os
import shutil
import subprocess

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") if os.name != "nt" else "C:/Program Files/Git/bin/bash.exe"


def test_update_locks_before_reading_current_or_mutating_directories() -> None:
    script = (PROJECT_ROOT / "release/deploy-update.template.sh").read_text(encoding="utf-8")
    assert script.index("flock -n 9") < script.index('PREVIOUS_RELEASE="$(readlink')
    assert script.index("flock -n 9") < script.index('mkdir -p "$RELEASE_DIR"')
    assert 'mv -- "$path" "$archived"' not in script
    assert "httpx.Client(trust_env=False).close()" in script
    assert 'PIP_CACHE_DIR="$APP_ROOT/cache/pip"' in script
    assert 'install -d -o root -g root -m 0755 "$PIP_CACHE_DIR"' in script
    assert "response.read()" in script
    assert "hashlib.sha256(data)" in script


@pytest.mark.parametrize("kind", ["live", "abandoned", "backup"])
def test_existing_release_or_backup_is_immutable(tmp_path: Path, kind: str) -> None:
    if not BASH or not Path(BASH).exists():
        pytest.skip("bash unavailable")
    release, backup = tmp_path / "release", tmp_path / "backup"
    target = backup if kind == "backup" else release
    target.mkdir()
    sentinel = target / "sentinel"
    sentinel.write_text("running-process-content")
    template = (PROJECT_ROOT / "release/deploy-update.template.sh").read_text(encoding="utf-8")
    guard = template[template.index('if [[ "$PREVIOUS_RELEASE"'):template.index('for unit in ')]
    script = tmp_path / "guard.sh"
    script.write_text('set -eu\nfail() { exit 23; }\nRELEASE_DIR=release\nBACKUP_DIR=backup\n'
                      + f'PREVIOUS_RELEASE={"release" if kind == "live" else "old"}\n'
                      + guard + '\necho UNEXPECTED_MUTATION\n', encoding="utf-8", newline="\n")
    result = subprocess.run([BASH, "guard.sh"], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 23, result.stderr
    assert "UNEXPECTED_MUTATION" not in result.stdout
    assert sentinel.read_text() == "running-process-content"
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([target.name, "guard.sh"])


def test_initial_installer_rejects_existing_installation_before_mutation() -> None:
    script = (PROJECT_ROOT / "release/deploy-nicokara-from-data.sh").read_text(encoding="utf-8")
    assert script.index("flock -n 9") < script.index('if [[ -e "$APP_ROOT/current"')
    assert script.index('if [[ -e "$APP_ROOT/current"') < script.index('tar -xzf "$APP_ARCHIVE"')
    assert 'mv -- "$RELEASE_DIR"' not in script
    assert 'systemctl stop nicokara-frontend nicokara-backend' not in script
