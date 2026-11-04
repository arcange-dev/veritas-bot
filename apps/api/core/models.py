"""Shared model primitives. Every domain model inherits from these."""
from __future__ import annotations

import uuid

from django.db import models


class UUIDModel(models.Model):
    """UUID primary key. Sequential ids leak volume and invite enumeration."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OrgScopedModel(UUIDModel, TimeStampedModel):
    """Anything a tenant owns. `organization` is the tenancy root.

    Querysets for these models must go through core.tenancy.for_org().
    """

    organization = models.ForeignKey(
        "identity.Organization",
        on_delete=models.PROTECT,
        related_name="%(class)ss",
        db_index=True,
    )

    class Meta:
        abstract = True
