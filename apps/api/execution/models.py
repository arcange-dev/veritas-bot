from __future__ import annotations

from django.db import models

from core.models import OrgScopedModel, TimeStampedModel, UUIDModel


class LocalRunnerDevice(OrgScopedModel):
    name = models.CharField(max_length=120)
    fingerprint = models.CharField(max_length=64)          # hashed, never the hostname
    os = models.CharField(max_length=40, blank=True)
    arch = models.CharField(max_length=40, blank=True)
    runner_version = models.CharField(max_length=40, blank=True)
    paired_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, related_name="devices"
    )
    paired_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    workspace_roots = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "execution_device"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "fingerprint"], name="uniq_device_org_fingerprint"
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class PairingCode(UUIDModel, TimeStampedModel):
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.CASCADE, related_name="pairing_codes"
    )
    code_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        "identity.Profile", on_delete=models.CASCADE, related_name="+"
    )
    expires_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by_device = models.ForeignKey(
        LocalRunnerDevice, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "execution_pairing_code"
        indexes = [models.Index(fields=["expires_at"], name="idx_pairing_expires")]


class ExecutionSession(UUIDModel, TimeStampedModel):
    """One execution environment, local or cloud, for one run."""

    run = models.ForeignKey(
        "orchestration.AgentRun", on_delete=models.CASCADE, related_name="sessions"
    )
    backend = models.CharField(
        max_length=20, choices=[("local", "Local runner"), ("cloud", "Cloud sandbox")]
    )
    status = models.CharField(
        max_length=20,
        choices=[("provisioning", "Provisioning"), ("ready", "Ready"),
                 ("busy", "Busy"), ("stopped", "Stopped"), ("failed", "Failed")],
        default="provisioning",
    )
    device = models.ForeignKey(
        LocalRunnerDevice, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sessions",
    )
    external_id = models.CharField(max_length=120, blank=True)
    workspace_path = models.CharField(max_length=500, blank=True)
    preview_url = models.URLField(blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "execution_session"
        indexes = [
            models.Index(fields=["run", "status"], name="idx_session_run_status"),
            models.Index(fields=["expires_at"], name="idx_session_expires"),
        ]


class CloudSandbox(UUIDModel, TimeStampedModel):
    session = models.OneToOneField(
        ExecutionSession, on_delete=models.CASCADE, related_name="sandbox"
    )
    provider = models.CharField(max_length=30, default="daytona")
    external_id = models.CharField(max_length=120, db_index=True)
    region = models.CharField(max_length=40, blank=True)
    image = models.CharField(max_length=200)
    cpu = models.DecimalField(max_digits=4, decimal_places=2, default=1)
    memory_gb = models.DecimalField(max_digits=4, decimal_places=2, default=2)
    disk_gb = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    expires_at = models.DateTimeField()
    destroyed_at = models.DateTimeField(null=True, blank=True)
    cost_accrual_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)

    class Meta:
        db_table = "execution_sandbox"
        indexes = [models.Index(fields=["expires_at"], name="idx_sandbox_expires")]
