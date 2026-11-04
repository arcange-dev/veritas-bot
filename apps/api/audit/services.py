"""Append-only audit writing. Called by privileged actions, never by the model."""
from __future__ import annotations

from typing import Any

from audit.models import AuditLog


def record_audit(*, action: str, organization=None, actor=None, target_type: str = "",
                 target_id: str = "", metadata: dict[str, Any] | None = None,
                 request_id: str = "", actor_type: str = "user") -> AuditLog:
    return AuditLog.objects.create(
        action=action,
        organization=organization,
        actor_profile=actor if getattr(actor, "pk", None) else None,
        actor_type=actor_type,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata or {},
        request_id=request_id,
    )
