from __future__ import annotations

from django.db import models

from core.models import UUIDModel


class ToolInvocation(UUIDModel, models.Model):
    """Audit row per tool call. Args are stored hashed plus a redacted preview."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    run = models.ForeignKey(
        "orchestration.AgentRun", on_delete=models.CASCADE,
        related_name="tool_invocations", null=True, blank=True,
    )
    step = models.ForeignKey(
        "orchestration.AgentStep", on_delete=models.CASCADE,
        related_name="tool_invocations", null=True, blank=True,
    )
    tool_name = models.CharField(max_length=80, db_index=True)
    args_hash = models.CharField(max_length=64)
    args_preview = models.JSONField(default=dict)          # redacted
    allowed = models.BooleanField(default=False)
    denied_reason = models.CharField(max_length=120, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(default=0)
    output_bytes = models.PositiveIntegerField(default=0)
    truncated = models.BooleanField(default=False)
    approval = models.ForeignKey(
        "orchestration.ApprovalRequest", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="tool_invocations",
    )

    class Meta:
        db_table = "tools_invocation"
        indexes = [
            models.Index(fields=["run", "created_at"], name="idx_tool_run_created"),
            models.Index(fields=["tool_name"], name="idx_tool_name"),
        ]
