from __future__ import annotations

from collections import defaultdict
from threading import Lock

from app.core.database import Database


class ActiveJobLimitError(RuntimeError):
    """Raised when one client already owns its allowed active job slots."""


class ActiveJobReservation:
    def __init__(self, limiter: "ActiveJobLimiter", client_key: str) -> None:
        self._limiter = limiter
        self._client_key = client_key
        self._active = True

    def commit(self) -> None:
        self.release()

    def release(self) -> None:
        if self._active:
            self._active = False
            self._limiter._release(self._client_key)


class ActiveJobLimiter:
    def __init__(self, *, database: Database, max_active_jobs: int) -> None:
        self.database = database
        self.max_active_jobs = max_active_jobs
        self._reservations: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def reserve(self, client_key: str) -> ActiveJobReservation:
        with self._lock:
            active_jobs = self.database.count_active_jobs_for_client(client_key)
            if active_jobs + self._reservations[client_key] >= self.max_active_jobs:
                raise ActiveJobLimitError(
                    "The client already has the maximum number of active jobs"
                )
            self._reservations[client_key] += 1
        return ActiveJobReservation(self, client_key)

    def _release(self, client_key: str) -> None:
        with self._lock:
            count = self._reservations.get(client_key, 0)
            if count <= 0:
                raise RuntimeError("Active job reservation accounting is invalid")
            if count == 1:
                self._reservations.pop(client_key, None)
            else:
                self._reservations[client_key] = count - 1
