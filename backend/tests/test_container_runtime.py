from pathlib import Path


def test_backend_image_installs_noto_cjk_for_ass_rendering() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "fonts-noto-cjk" in dockerfile


def test_backend_image_does_not_require_a_regional_apt_mirror() -> None:
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "ARG DEBIAN_MIRROR=" in dockerfile
    assert 'if [ -n "$DEBIAN_MIRROR" ]' in dockerfile
    assert "ARG DEBIAN_MIRROR=mirrors.aliyun.com" not in dockerfile
    assert "Acquire::Retries=5" in dockerfile
    assert "--mount=type=cache,target=/var/cache/apt" in dockerfile


def test_compose_enables_restart_init_security_and_log_rotation() -> None:
    compose = (Path(__file__).parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert compose.count("restart: unless-stopped") == 2
    assert compose.count("init: true") == 2
    assert compose.count("no-new-privileges:true") == 2
    assert "max-size: \"10m\"" in compose
    assert "max-file: \"3\"" in compose


def test_frontend_container_excludes_and_cleans_stale_build_output() -> None:
    project_root = Path(__file__).resolve().parents[2]
    dockerignore = (
        project_root / "frontend" / ".dockerignore"
    ).read_text(encoding="utf-8")
    dockerfile = (
        project_root / "frontend" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "dist" in dockerignore.splitlines()
    assert "RUN rm -rf dist" in dockerfile


def test_backend_installs_mdx_net_and_persists_model_cache() -> None:
    project_root = Path(__file__).resolve().parents[2]
    pyproject = (
        project_root / "backend" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    dockerfile = (
        project_root / "backend" / "Dockerfile"
    ).read_text(encoding="utf-8")
    compose = (project_root / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert "audio-separator[cpu]" in pyproject
    assert "build-essential" in dockerfile
    assert "NICOKARA_VOCAL_REMOVAL_BACKEND: mdx" in compose
    assert "mdx-model-cache:/app/models/audio-separator" in compose
    assert "mdx-model-cache:" in compose


def test_backend_dependency_layer_is_reused_for_app_only_changes() -> None:
    dockerfile = (
        Path(__file__).parents[1] / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert dockerfile.index('pip install --no-cache-dir ".[ai]"') < (
        dockerfile.index("COPY app ./app")
    )


def test_backend_installs_mms_fa_and_persists_its_model_cache() -> None:
    project_root = Path(__file__).resolve().parents[2]
    pyproject = (project_root / "backend" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    dockerfile = (project_root / "backend" / "Dockerfile").read_text(
        encoding="utf-8"
    )
    compose = (project_root / "docker-compose.yml").read_text(
        encoding="utf-8"
    )

    assert 'torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1' in dockerfile
    assert 'torchaudio>=2.7.1,<2.8' in pyproject
    assert 'NICOKARA_FA_KARA_ENABLED: ${NICOKARA_FA_KARA_ENABLED:-true}' in compose
    assert 'mms-model-cache:/root/.cache/torch' in compose
    assert 'mms-model-cache:' in compose
