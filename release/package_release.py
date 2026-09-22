"""Package a clean committed checkout and its fresh standalone frontend build."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def main() -> None:
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("Commit tracked changes before packaging.")
    source = git("rev-parse", "HEAD").decode().strip()
    tracked = git("ls-files", "-z").decode().split("\0")
    standalone = ROOT / "frontend/dist/standalone"
    server = standalone / "server.js"
    if not server.is_file():
        raise SystemExit("Run the production frontend build first.")
    for name in tracked:
        if name.startswith("frontend/") and (ROOT / name).stat().st_mtime > server.stat().st_mtime:
            raise SystemExit(f"Build is older than {name}; rebuild before packaging.")
    version = json.loads(git("show", "HEAD:frontend/package.json"))["version"]
    release_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    release_name = f"nicokara-cloud-v{version}-{source[:7]}-{release_id}"
    output = ROOT / "release"
    archive_path = output / f"{release_name}.tar.gz"
    hashes: dict[str, str] = {}
    with tarfile.open(archive_path, "x:gz", format=tarfile.PAX_FORMAT) as archive:
        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(f"nicokara/{name}")
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
            hashes[name] = hashlib.sha256(data).hexdigest()

        for file in sorted(standalone.rglob("*")):
            if not file.is_file():
                continue
            relative = file.relative_to(standalone)
            if file.is_symlink() or ".env" in file.name or any(p in {".cache", "__pycache__", ".git"} for p in relative.parts):
                raise SystemExit(f"Unexpected file in build output: {relative}")
            add(f"frontend/{relative.as_posix()}", file.read_bytes())
        for name in tracked:
            if name.startswith(("backend/app/", "backend/config/")) or name in {
                "backend/pyproject.toml", "README.md", "CHANGELOG.md", "THIRD_PARTY_NOTICES.md",
            }:
                if ".env" in Path(name).name or Path(name).suffix in {".sqlite3", ".pyc"}:
                    raise SystemExit(f"Unexpected source file: {name}")
                add(name, git("show", f"HEAD:{name}"))
        add("SOURCE_COMMIT.txt", f"{source}\n".encode())
        add("RELEASE_MANIFEST.json", json.dumps({
            "version": version, "release_id": release_id, "source_commit": source,
            "frontend_api": "/api/v1", "target": "Linux systemd /data/nicokara",
            "models_included": False, "secrets_included": False,
        }, indent=2).encode())
        add("FILE_SHA256SUMS", "".join(f"{digest}  {name}\n" for name, digest in sorted(hashes.items())).encode())
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    checksum = output / f"{release_name}.tar.gz.sha256"
    checksum.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8", newline="\n")
    template = git("show", "HEAD:release/deploy-update.template.sh").decode()
    for key, value in {"RELEASE_ID": release_id, "SOURCE_COMMIT": source,
                       "ARCHIVE_NAME": archive_path.name, "SHA256": digest}.items():
        template = template.replace(f"@@{key}@@", value)
    script = output / f"deploy-{release_name}.sh"
    script.write_text(template, encoding="utf-8", newline="\n")
    instructions = output / f"部署说明-v{version}-{source[:7]}-{release_id}.md"
    instructions.write_text(f"""# 本次部署

- 源码提交：`{source}`
- 包校验值：`{digest}`
- 适用于现有 `/data/nicokara`、systemd、Nginx 部署，Node.js 建议 24，Python >=3.11。
- 模型、密钥、数据库与任务文件不包含在包内，继续使用服务器已有文件。
- 工作进程数量及现有公告保持不变；升级前需等待队列任务完成。

在本机 PowerShell 执行（替换 `SERVER_IP` 和 SSH 用户）：

```powershell
scp \"{archive_path}\" \"{script}\" \"{checksum}\" root@SERVER_IP:/data/
ssh root@SERVER_IP
```

登录服务器后执行：

```bash
cd /data
sha256sum -c {checksum.name}
bash {script.name} https://www.nicokara.icu
systemctl is-active nicokara-backend nicokara-frontend
curl -fsS http://127.0.0.1:8000/health
```

脚本创建新版本环境，先安装依赖，再停止服务、备份 SQLite 与配置、切换版本并检查健康状态。
健康检查失败会尝试恢复旧版本及配置。数据库不会自动倒退，备份在
`/data/nicokara/backups/{release_id}/`，任务文件和模型不删除。
已有同名发布目录或备份目录会自动改名为带 `.previous-` 后缀的保留目录，
然后创建干净目录继续部署；失败的发布目录也会保留用于排查。
首次部署请按项目中的 `DEPLOYMENT_LOCAL_BUILD.md` 准备基础环境。
""", encoding="utf-8", newline="\n")
    print(json.dumps({"archive": str(archive_path), "script": str(script), "checksum": str(checksum),
                      "instructions": str(instructions), "sha256": digest, "commit": source,
                      "size_bytes": archive_path.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
