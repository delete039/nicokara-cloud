from __future__ import annotations

import os
from pathlib import Path
import shutil


def _memory_snapshot() -> dict[str, int | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            key, raw_value = line.split(":", 1)
            values[key] = int(raw_value.strip().split()[0]) * 1024
    except (OSError, ValueError):
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
        }

    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": (
            total - available
            if total is not None and available is not None
            else None
        ),
    }


def collect_system_resources(storage_dir: Path) -> dict:
    disk = shutil.disk_usage(storage_dir)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except (AttributeError, OSError):
        load_1m = load_5m = load_15m = None
    return {
        "cpu_count": os.cpu_count(),
        "load_average": {
            "one_minute": load_1m,
            "five_minutes": load_5m,
            "fifteen_minutes": load_15m,
        },
        "memory": _memory_snapshot(),
        "disk": {
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
    }
