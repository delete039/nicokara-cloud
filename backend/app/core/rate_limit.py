from __future__ import annotations

from ipaddress import ip_address, ip_network


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
