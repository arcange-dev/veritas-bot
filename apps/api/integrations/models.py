"""Webhook bookkeeping for the GitHub integration.

There is intentionally no Installation/Repository model here: `projects.models`
already owns Repository (and RepositoryIndex) and Deployment, and this app only
reads them. This app owns exactly one table — the inbox that proves a webhook
was received, verified and understood.

Why the payload itself is not stored
------------------------------------
A GitHub payload is third-party content of unknown shape and size, and the
delivery log is read by every member of the workspace. Storing a digest plus a
few selected fields keeps the audit trail (what arrived, when, was the signature
valid, was it a replay) without turning the table into a copy of other people's
code. Nothing secret is ever written here.
"""
from __future__ import annotations

from django.db import models

from core.models import TimeStampedModel, UUIDModel


class WebhookDeliveryStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    IGNORED = "ignored", "Ignored"          # a real event we do not act on
    REJECTED = "rejected", "Rejected"       # bad signature / replay, recorded for triage


class WebhookDelivery(UUIDModel, TimeStampedModel):
    """One row per accepted GitHub webhook delivery.

    `delivery_id` is UNIQUE on purpose: GitHub sends `X-GitHub-Delivery` once per
    delivery, so a second request carrying the same id is a replay, and the
    database — not application code — is what refuses it. That makes the check
    race-free under concurrent retries.
    """

    # 64 chars covers GitHub's uuid-shaped delivery ids with room to spare.
    delivery_id = models.CharField(max_length=64, unique=True)
    event = models.CharField(max_length=40, db_index=True)
    action = models.CharField(max_length=40, blank=True)

    # No organization FK. The webhook arrives unauthenticated, before any tenant
    # is known, so an org link here would be a guess. Org scoping happens at read
    # time: a tenant sees deliveries whose installation_id belongs to one of its
    # own repositories (see integrations.views).
    installation_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    repository_full_name = models.CharField(max_length=200, blank=True)
    ref = models.CharField(max_length=200, blank=True)
    commit_sha = models.CharField(max_length=40, blank=True)
    pull_request_number = models.PositiveIntegerField(null=True, blank=True)

    payload_digest = models.CharField(max_length=64, blank=True)
    signature_verified = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20, choices=WebhookDeliveryStatus.choices,
        default=WebhookDeliveryStatus.RECEIVED,
    )
    summary = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "integrations_webhook_delivery"
        indexes = [models.Index(fields=["-created_at"], name="idx_webhook_delivery_created")]

    def __str__(self) -> str:
        return f"{self.event}:{self.delivery_id}"
