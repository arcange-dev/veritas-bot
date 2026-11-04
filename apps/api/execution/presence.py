"""Which runner devices are connected right now.

The channel layer knows; the database does not. Presence lives in the cache with
a short TTL so a hard-killed runner disappears without anyone cleaning up.
"""
from __future__ import annotations

from django.core.cache import cache

TTL_SECONDS = 45


def _key(device_id: str) -> str:
    return f"runner:online:{device_id}"


def mark_online(device_id: str) -> None:
    cache.set(_key(device_id), True, timeout=TTL_SECONDS)


def mark_offline(device_id: str) -> None:
    cache.delete(_key(device_id))


def is_online(device_id: str) -> bool:
    return bool(cache.get(_key(device_id)))
