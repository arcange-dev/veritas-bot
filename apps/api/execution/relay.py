"""Correlated request/response between Django and a paired runner device.

Every call gets its own reply channel created by the server. The runner is never
told where to publish and can never address another caller: it only answers on
the socket it opened, and the consumer does the routing.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from asgiref.sync import async_to_sync

from execution.presence import is_online

DEFAULT_TIMEOUT_SECONDS = 120.0


class RelayError(RuntimeError):
    """Base class for relay failures that callers are expected to handle."""


class DeviceOffline(RelayError):
    pass


class DeviceTimeout(RelayError):
    pass


class RunnerRefused(RelayError):
    """The runner answered but rejected the work: policy, path, missing approval."""


def device_group(device_id: str) -> str:
    return f"device.{device_id}"


def session_group(session_id: str) -> str:
    return f"session.{session_id}"


class RunnerRelay:
    def __init__(self, channel_layer=None) -> None:
        if channel_layer is None:
            from channels.layers import get_channel_layer

            channel_layer = get_channel_layer()
        self.channel_layer = channel_layer

    async def request(
        self,
        device_id: str,
        frame: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        require_online: bool = True,
    ) -> dict[str, Any]:
        """Send one frame and await its matching result frame.

        Raises DeviceOffline before touching the network when presence is stale,
        so a queued task does not burn its whole timeout on a dead laptop.
        """
        if require_online and not is_online(str(device_id)):
            raise DeviceOffline(f"runner {device_id} is not connected")

        reply_channel = await self.channel_layer.new_channel()
        request_id = str(frame.get("id") or uuid.uuid4().hex)
        outbound = {**frame, "id": request_id, "v": int(frame.get("v", 1))}

        await self.channel_layer.group_send(
            device_group(str(device_id)),
            {
                "type": "relay.deliver",
                "reply_channel": reply_channel,
                "frame": outbound,
            },
        )

        try:
            payload = await asyncio.wait_for(
                self.channel_layer.receive(reply_channel), timeout=timeout
            )
        except asyncio.TimeoutError as exc:
            raise DeviceTimeout(
                f"runner {device_id} did not answer within {timeout:.0f}s"
            ) from exc

        result = payload.get("payload", payload)
        if not result.get("ok", False):
            raise RunnerRefused(str(result.get("error") or "runner refused the request"))
        return dict(result.get("data") or {})

    def request_sync(
        self,
        device_id: str,
        frame: dict[str, Any],
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        require_online: bool = True,
    ) -> dict[str, Any]:
        """Bridge for synchronous DRF views and Celery tasks."""
        return async_to_sync(self.request)(
            device_id, frame, timeout=timeout, require_online=require_online
        )
