from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from ipaddress import ip_address, ip_network
import math
from threading import Lock
import time

from app.core.database import Database


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


def _trusted_address(host: str, trusted_proxies: tuple[str, ...]) -> bool:
    if host in trusted_proxies:
        return True
    try:
        address = ip_address(host)
    except ValueError:
        return False
    for candidate in trusted_proxies:
        try:
            if address in ip_network(candidate, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolve_client_key(
    *,
    peer_host: str,
    forwarded_for: str | None,
    trusted_proxies: tuple[str, ...],
) -> str:
    if not forwarded_for or not _trusted_address(peer_host, trusted_proxies):
        return peer_host

    forwarded_addresses: list[str] = []
    for value in forwarded_for.split(","):
        candidate = value.strip()
        try:
            forwarded_addresses.append(str(ip_address(candidate)))
        except ValueError:
            continue

    for candidate in reversed([*forwarded_addresses, peer_host]):
        if not _trusted_address(candidate, trusted_proxies):
            return candidate
    return peer_host


class UploadRateLimiter:
    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: int,
        database: Database | None = None,
    ) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.database = database
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        timestamp = time.time() if now is None else now
        if self.database is not None:
            allowed, retry_after = self.database.consume_upload_limit(
                key,
                max_requests=self.max_requests,
                window_seconds=self.window_seconds,
                now=timestamp,
            )
            return RateLimitDecision(allowed, retry_after)

        cutoff = timestamp - self.window_seconds
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.max_requests:
                retry_after = max(
                    1,
                    math.ceil(requests[0] + self.window_seconds - timestamp),
                )
                return RateLimitDecision(False, retry_after)
            requests.append(timestamp)
            return RateLimitDecision(True, 0)

    def allow(self, key: str, *, now: float | None = None) -> bool:
        return self.check(key, now=now).allowed
