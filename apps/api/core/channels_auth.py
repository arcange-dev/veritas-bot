"""WebSocket authentication for the runner channel.

Rejects the socket during the handshake rather than silently accepting and
closing later, and never logs the token.
"""
from __future__ import annotations

import logging

from urllib.parse import parse_qs

logger = logging.getLogger(__name__)


class RunnerAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)

        from channels.db import database_sync_to_async
        from rest_framework.exceptions import AuthenticationFailed

        from execution.tokens import verify_runner_token

        query = parse_qs(scope.get("query_string", b"").decode())
        token = (query.get("token") or [""])[0]
        device_id = (query.get("device") or [""])[0]

        if not token or not device_id:
            scope["code"] = 4401
            return await send({"type": "websocket.close", "code": 4401})

        try:
            device = await database_sync_to_async(verify_runner_token)(token, device_id)
        except AuthenticationFailed:
            scope["code"] = 4401
            return await send({"type": "websocket.close", "code": 4401})
        except Exception:
            logger.exception("runner auth failure")
            return await send({"type": "websocket.close", "code": 1011})

        scope["device"] = device
        return await self.app(scope, receive, send)
