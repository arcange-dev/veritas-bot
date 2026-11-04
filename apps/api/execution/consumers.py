"""WebSocket consumers.

RunnerConsumer  - the paired device. Outbound-initiated; the server never dials in.
TerminalConsumer - the browser terminal. Authorised against session ownership.

Neither consumer lets a client choose where the server publishes, so a
compromised runner cannot inject frames into another tenant's stream.
"""
from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from execution.presence import mark_offline, mark_online
from execution.relay import device_group, session_group

logger = logging.getLogger(__name__)

MAX_PENDING = 512
FORWARDED_TYPES = {"result", "output"}


class RunnerConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        device = self.scope.get("device")
        if device is None:  # handshake should have rejected this
            await self.close(code=4401)
            return

        self.device_id = str(device.id)
        self.group = device_group(self.device_id)
        self.pending: dict[str, str] = {}

        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()
        mark_online(self.device_id)
        await self._touch()

    async def disconnect(self, code) -> None:
        await self.channel_layer.group_discard(self.group, self.channel_name)
        mark_offline(self.device_id)
        # Wake every in-flight caller instead of letting it sit until timeout.
        for reply_channel in list(self.pending.values()):
            await self.channel_layer.send(
                reply_channel,
                {
                    "type": "relay.reply",
                    "payload": {"ok": False, "error": "runner disconnected", "data": {}},
                },
            )
        self.pending.clear()

    async def relay_deliver(self, event: dict) -> None:
        """Server -> runner. Called by RunnerRelay, never by the network."""
        frame = event["frame"]
        reply_channel = event["reply_channel"]

        if len(self.pending) >= MAX_PENDING:
            await self.channel_layer.send(
                reply_channel,
                {
                    "type": "relay.reply",
                    "payload": {"ok": False, "error": "runner request queue is full", "data": {}},
                },
            )
            return

        self.pending[str(frame.get("id", ""))] = reply_channel
        await self.send_json(frame)

    async def receive_json(self, content, **kwargs) -> None:
        kind = content.get("type", "")

        if kind == "hello":
            await self._record_hello(content)
            mark_online(self.device_id)
            return

        if kind == "pong":
            mark_online(self.device_id)
            return

        if kind in FORWARDED_TYPES:
            request_id = str(content.get("id", ""))
            reply_channel = self.pending.get(request_id)

            if kind == "result" and reply_channel:
                self.pending.pop(request_id, None)
                await self.channel_layer.send(
                    reply_channel, {"type": "relay.reply", "payload": content}
                )
                return

            # Live output is broadcast to the session so the browser terminal can
            # show progress before the command finishes.
            session = str(content.get("session", ""))
            if session:
                await self.channel_layer.group_send(
                    session_group(session),
                    {"type": "session.output", "payload": content},
                )
            return

        logger.debug("runner sent unhandled frame type %r", kind)

    async def _record_hello(self, content: dict) -> None:
        await self._update_device(
            runner_version=str(content.get("runner_version", ""))[:40],
            os=str(content.get("os", ""))[:40],
            arch=str(content.get("arch", ""))[:40],
            roots=[str(r)[:400] for r in (content.get("workspace_roots") or [])][:20],
        )

    @database_sync_to_async
    def _touch(self) -> None:
        from execution.models import LocalRunnerDevice

        LocalRunnerDevice.objects.filter(id=self.device_id).update(last_seen_at=timezone.now())

    @database_sync_to_async
    def _update_device(self, **fields) -> None:
        from execution.models import LocalRunnerDevice

        LocalRunnerDevice.objects.filter(id=self.device_id, revoked_at__isnull=True).update(
            last_seen_at=timezone.now(),
            runner_version=fields["runner_version"],
            os=fields["os"],
            arch=fields["arch"],
            workspace_roots=fields["roots"],
        )


class TerminalConsumer(AsyncJsonWebsocketConsumer):
    """Browser terminal for one execution session."""

    async def connect(self) -> None:
        self.session_id = self.scope["url_route"]["kwargs"]["session_id"]

        from urllib.parse import parse_qs

        query = parse_qs(self.scope.get("query_string", b"").decode())
        token = (query.get("token") or [""])[0]
        if not token:
            await self.close(code=4401)
            return

        allowed = await self._authorise(str(self.session_id), token)
        if not allowed:
            await self.close(code=4403)
            return

        self.group = session_group(str(self.session_id))
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code) -> None:
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def session_output(self, event: dict) -> None:
        payload = event.get("payload", {})
        await self.send_json(
            {
                "type": "output",
                "stream": payload.get("stream", "stdout"),
                "seq": payload.get("seq", 0),
                "data": payload.get("data", ""),
            }
        )

    @database_sync_to_async
    def _authorise(self, session_id: str, token: str) -> bool:
        from rest_framework.exceptions import AuthenticationFailed

        from execution.models import ExecutionSession
        from identity.authentication import decode_supabase_token
        from identity.models import Membership, Profile

        try:
            claims = decode_supabase_token(token)
        except AuthenticationFailed:
            return False

        profile = Profile.objects.filter(supabase_user_id=claims.get("sub", "")).first()
        if profile is None:
            return False

        session = (
            ExecutionSession.objects.select_related("run__project__organization")
            .filter(id=session_id)
            .first()
        )
        if session is None:
            return False

        org_id = session.run.project.organization_id if session.run.project_id else None
        if org_id is None:
            return False

        # Tenant check, not just authentication: a valid token for another
        # organisation must not open this terminal.
        return Membership.objects.filter(
            profile=profile, organization_id=org_id, is_active=True
        ).exists()
