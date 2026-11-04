from __future__ import annotations

from django.db import models

from core.models import UUIDModel


class AuditLog(UUIDModel, models.Model):
    """Append-only. Nothing in the application code updates or deletes these."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.PROTECT,
        related_name="audit_logs", null=True, blank=True,
    )
    actor_profile = models.ForeignKey(
        "identity.Profile", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    actor_type = models.CharField(
        max_length=20,
        choices=[("user", "User"), ("agent", "Agent"), ("system", "System"),
                 ("device", "Device")],
        default="user",
    )
    action = models.CharField(max_length=80, db_index=True)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)   # never credentials
    ip_hash = models.CharField(max_length=64, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="idx_audit_org_created"),
            models.Index(fields=["action"], name="idx_audit_action"),
        ]


class Notification(UUIDModel, models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.CASCADE, related_name="notifications"
    )
    profile = models.ForeignKey(
        "identity.Profile", on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=40)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "audit_notification"
        indexes = [models.Index(fields=["profile", "read_at"], name="idx_notif_profile_read")]
