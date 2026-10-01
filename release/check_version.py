"""Check that the project version is consistent across source metadata."""
from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def main() -> None:
    version = read("VERSION").strip()
    if not re.fullmatch(r"\d+\.\d+", version):
        raise SystemExit(f"VERSION must be numeric major.minor, got: {version!r}")

    frontend = json.loads(read("frontend/package.json"))["version"]
    lock = json.loads(read("frontend/package-lock.json"))
    lock_version = lock["version"]
    backend = re.search(r'^version\s*=\s*"([^"]+)"$', read("backend/pyproject.toml"), re.MULTILINE)
    api = re.search(r'version="([^"]+)"', read("backend/app/main.py"))
    readme = re.search(r"当前版本：`v([^`]+)`", read("README.md"))
    announcement = json.loads(read("frontend/public/announcement.json"))

    found = {
        "frontend/package.json": frontend,
        "frontend/package-lock.json": lock_version,
        "backend/pyproject.toml": backend.group(1) if backend else None,
        "backend/app/main.py": api.group(1) if api else None,
        "README.md": readme.group(1) if readme else None,
        "frontend/public/announcement.json": announcement.get("version", "").removeprefix("v"),
    }
    mismatches = {
        path: value
        for path, value in found.items()
        if value != version
    }
    if mismatches:
        details = ", ".join(f"{path}={value!r}" for path, value in mismatches.items())
        raise SystemExit(f"Version mismatch: expected {version!r}; {details}")

    print(f"Version OK: v{version}")


if __name__ == "__main__":
    main()
