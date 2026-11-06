"""Bind the database's row-level security context to the current transaction.

This module is the trust boundary for tenant isolation. The policies in
core/migrations trust `app.current_org` and `app.current_profile` completely, so
the ONLY code allowed to set them is here, and `bind_tenant` refuses to do so
unless the caller is an active member of that organization.

Why transaction-local, never session-local
------------------------------------------
`set_config(name, value, true)` lasts until the transaction ends. Connections
are pooled and reused across requests; a session-level setting would carry one
tenant's identity into the next request on that connection. Transaction-local
settings cannot outlive the unit of work, so they cannot leak.

Because the setting dies with the transaction, anything that depends on it must
run inside `tenant_context()`, which opens the transaction.
"""
from __future__ import annotations

import contextlib
import uuid
from typing import Iterator

from django.db import connection, transaction


class TenantBindingError(PermissionError):
    """The caller may not act as that tenant. Never swallow this."""


def _as_uuid(value) -> str:
    # Normalising here also rejects anything that is not a UUID before it can
    # reach SQL, so a malformed id fails in Python rather than in a policy.
    return str(uuid.UUID(str(value)))


def _set(profile_id: str | None, org_id: str | None) -> None:
    if connection.vendor != "postgresql":
        return                                  # SQLite has no RLS; ORM scoping applies
    with connection.cursor() as cur:
        cur.execute("SELECT set_config('app.current_profile', %s, true)", [profile_id or ""])
        cur.execute("SELECT set_config('app.current_org', %s, true)", [org_id or ""])


def _is_active_member(profile_id: str, org_id: str) -> bool:
    """Membership is checked with the profile context set but no org yet.

    identity_membership is itself protected by org-scoped RLS, so this lookup
    has to happen as the platform, before the tenant is bound. It reads exactly
    one row and returns a boolean; nothing from it reaches the caller.
    """
    from identity.models import Membership

    return Membership.objects.filter(
        profile_id=profile_id, organization_id=org_id, is_active=True
    ).exists()


@contextlib.contextmanager
def tenant_context(*, profile, org) -> Iterator[None]:
    """Run a block inside a transaction bound to (profile, org).

    Raises TenantBindingError if the profile is not an active member of org.
    The settings are reset on exit even if the body raises.
    """
    if profile is None or org is None:
        raise TenantBindingError("a profile and an organization are both required")

    profile_id = _as_uuid(getattr(profile, "pk", profile))
    org_id = _as_uuid(getattr(org, "pk", org))

    with transaction.atomic():
        # Identify the caller first. Membership rows are visible to their owner
        # via the profile policy path, so the check below is meaningful.
        _set(profile_id, None)
        if not _is_active_member(profile_id, org_id):
            raise TenantBindingError("not a member of that organization")
        _set(profile_id, org_id)
        # No cleanup SQL: the settings are transaction-local, so leaving the
        # atomic block (commit OR rollback) discards them. Running a query here
        # would fail on a transaction that has been marked for rollback.
        yield


@contextlib.contextmanager
def profile_context(*, profile) -> Iterator[None]:
    """Bind only the caller's identity (login, listing their own organizations)."""
    if profile is None:
        raise TenantBindingError("a profile is required")
    profile_id = _as_uuid(getattr(profile, "pk", profile))
    with transaction.atomic():
        _set(profile_id, None)
        yield


class TenantBoundMixin:
    """Run an org-scoped DRF view inside a transaction bound to its tenant.

    DRF authenticates inside the view, after Django middleware, so middleware
    cannot know who the caller is. `initial()` runs after authentication and
    permission checks, so by then `request.membership` is already verified and
    this mixin only has to bind it, not re-check it.

    The transaction opens in `initial()` and closes in `finalize_response()`
    (which DRF calls on success AND on handled errors), so the tenant setting
    covers the whole handler and is gone before the connection is reused.
    """

    _tenant_cm = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        membership = getattr(request, "membership", None)
        if membership is None:
            return                              # not an org-scoped route
        cm = tenant_context(profile=membership.profile, org=membership.organization)
        cm.__enter__()
        self._tenant_cm = cm

    def _close_tenant(self, exc_info=(None, None, None)) -> None:
        cm, self._tenant_cm = self._tenant_cm, None
        if cm is not None:
            cm.__exit__(*exc_info)

    def finalize_response(self, request, response, *args, **kwargs):
        # Only a server error rolls back. A 4xx (validation, 404, 409) is a normal
        # answer, and the work done before it, such as an audit row, must commit.
        status_code = getattr(response, "status_code", 500)
        if self._tenant_cm is not None and status_code >= 500:
            from django.db import transaction
            transaction.set_rollback(True)
        self._close_tenant()
        return super().finalize_response(request, response, *args, **kwargs)


# --- ambient tenant for background work ---------------------------------------------
# A worker holds an identity for the whole run but must NOT hold a transaction
# open across it: runs last minutes and call remote models, and an open
# transaction keeps row locks that parallel task threads then block on (a real
# deadlock, caught in testing). So the identity lives in thread-local state and
# each database touchpoint opens its own short bound transaction.
import threading as _threading

_ambient = _threading.local()


@contextlib.contextmanager
def ambient_tenant(*, profile, org) -> Iterator[None]:
    """Declare who this thread acts as, without opening a transaction.

    Membership is verified up front (one short transaction) so a revoked member
    is refused before any work starts; each later `bound()` re-binds cheaply.
    """
    profile_id = _as_uuid(getattr(profile, "pk", profile))
    org_id = _as_uuid(getattr(org, "pk", org))
    with tenant_context(profile=profile_id, org=org_id):
        pass                                   # raises TenantBindingError if not a member
    previous = getattr(_ambient, "value", None)
    _ambient.value = (profile_id, org_id)
    try:
        yield
    finally:
        _ambient.value = previous


def current_ambient() -> tuple[str, str] | None:
    return getattr(_ambient, "value", None)


def set_ambient(value: tuple[str, str] | None) -> None:
    """Used by worker threads to adopt the identity their parent declared."""
    _ambient.value = value


@contextlib.contextmanager
def bound() -> Iterator[None]:
    """A short transaction bound to the ambient tenant, or a plain one if none.

    Re-entrant: inside an already-open atomic block it only re-asserts the
    settings, so nesting is cheap and never opens a second connection.
    """
    ident = current_ambient()
    if ident is None:
        with transaction.atomic():
            yield
        return
    profile_id, org_id = ident
    with transaction.atomic():
        _set(profile_id, org_id)
        yield


@contextlib.contextmanager
def login_context(*, subject) -> Iterator[None]:
    """Bind ONLY the verified token subject, for finding or creating that user's profile.

    Call this after the token's signature, audience and expiry have been verified and
    nowhere else. It does not identify a profile or a tenant; it lets exactly one
    supabase_user_id be looked up or inserted (see core migration 0005). The setting is
    transaction-local, so it is gone when the block ends.
    """
    value = _as_uuid(subject)
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cur:
                cur.execute("SELECT set_config('app.auth_subject', %s, true)", [value])
        yield
