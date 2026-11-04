"""The only sanctioned way to scope a queryset to a tenant."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.db.models import QuerySet, Model


def for_org(qs: "QuerySet", org) -> "QuerySet":
    """Scope a queryset to an organization.

    Accepts an Organization instance or a uuid. Raises ValueError on None so a
    missing org filter fails loudly instead of leaking every tenant's rows.
    """
    if org is None:
        raise ValueError("for_org() requires an organization; refusing to return unscoped rows")
    return qs.filter(organization=org)


def scoped_or_404(qs: "QuerySet", org, **lookup) -> "Model":
    """Fetch one row inside the tenant, or raise 404.

    Cross-tenant ids must produce 404 (not 403) so ids stay unenumerable.
    """
    from rest_framework.exceptions import NotFound

    row = for_org(qs, org).filter(**lookup).first()
    if row is None:
        raise NotFound("Not found")
    return row
