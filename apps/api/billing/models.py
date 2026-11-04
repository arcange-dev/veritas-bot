from __future__ import annotations

from django.db import models

from core.models import UUIDModel


class UsageRecord(UUIDModel, models.Model):
    """One row per model call. Cost comes from real token counts, not guesses."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    organization = models.ForeignKey(
        "identity.Organization", on_delete=models.CASCADE, related_name="usage_records"
    )
    run = models.ForeignKey(
        "orchestration.AgentRun", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="usage",
    )
    agent_kind = models.CharField(max_length=30, blank=True)
    provider = models.CharField(max_length=40)
    model_id = models.CharField(max_length=160)
    credential = models.ForeignKey(
        "providers.ProviderCredential", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="usage",
    )
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cached_tokens = models.BigIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    estimated = models.BooleanField(default=True)
    fallback_reason = models.CharField(max_length=120, blank=True)

    class Meta:
        db_table = "billing_usage"
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="idx_usage_org_created"),
            models.Index(fields=["run"], name="idx_usage_run"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(input_tokens__gte=0) & models.Q(output_tokens__gte=0),
                name="ck_usage_tokens_non_negative",
            )
        ]
