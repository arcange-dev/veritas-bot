"""Subscribe to a runner's live output for one session.

The browser never talks to a runner directly: it joins a session group and the
consumer publishes already-authorised output frames there.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from execution.relay import session_group


async def subscribe(session_id: str, channel_layer=None) -> AsyncIterator[dict]:
    """Yield output frames for a session until the caller stops consuming."""
    if channel_layer is None:
        from channels.layers import get_channel_layer

        channel_layer = get_channel_layer()

    channel_name = await channel_layer.new_channel()
    await channel_layer.group_add(session_group(str(session_id)), channel_name)
    try:
        while True:
            event = await channel_layer.receive(channel_name)
            if event.get("type") == "session.output":
                yield event.get("payload", {})
    finally:
        await channel_layer.group_discard(session_group(str(session_id)), channel_name)
