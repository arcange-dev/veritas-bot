"""Organization-aware permissions. 404 on failure to prevent id enumeration."""
from __future__ import annotations

from rest_framework.exceptions import NotAuthenticated, NotFound, PermissionDenied
from rest_framework.permissions import BasePermission

from identity.models import Membership

ADMIN_ROLES = {"owner", "admin"}
ALL_ROLES = {"owner", "admin", "member", "viewer"}


def resolve_membership(request, view=None):
    """Resolve and cache the caller's membership for the target org.

    The org id comes from the URL kwargs (via the DRF view, because DRF's
    Request has no `.kwargs`), then the X-Org-Id header, then the query string.
    """
    if getattr(request, "membership", None) is not None:
        return request.membership

    # "Who are you?" is a different question from "does this exist?". Anonymous
    # callers get 401 so a client knows to re-authenticate; only authenticated
    # callers get the enumeration-safe 404 below.
    if not getattr(request.user, "is_authenticated", False):
        raise NotAuthenticated()

    url_kwargs = getattr(view, "kwargs", None) or {}
    org_id = (
        url_kwargs.get("org_id")
        or request.headers.get("X-Org-Id")
        or request.query_params.get("org_id")
    )
    if not org_id:
        raise NotFound("Organization not specified")

    # request.user is a Profile (Supabase authentication), but stay tolerant
    # of a Django user object so management commands and tests can use either.
    from identity.models import Profile

    if isinstance(request.user, Profile):
        profile = request.user
    else:
        profile = getattr(request.user, "profile", None)
    if profile is None:
        raise NotFound("Not found")

    # Authorisation read. Under row-level security this must run with the
    # caller's identity bound and NO tenant yet: the membership row is visible
    # to its owner (membership_self_read), which is exactly the fact we need.
    # `select_related` is deliberately avoided: joining organization/profile
    # would filter the row out, because those tables are not visible until the
    # tenant is bound, which is what this check decides.
    from core.rls import profile_context

    with profile_context(profile=profile):
        membership = Membership.objects.filter(
            profile=profile, organization_id=org_id, is_active=True
        ).first()
    if membership is None:
        raise NotFound("Organization not found")

    # Membership is confirmed, so the organization may now be loaded. The
    # mixin binds the full tenant for the rest of the request; until then, read
    # the single org row inside a context bound to that verified pair.
    from core.rls import tenant_context

    with tenant_context(profile=profile, org=membership.organization_id):
        from identity.models import Organization

        membership.organization = Organization.objects.get(pk=membership.organization_id)
    membership.profile = profile

    request.membership = membership
    request.org = membership.organization
    return membership


class IsOrgMember(BasePermission):
    """Any active member of the organization in the URL or X-Org-Id header."""

    def has_permission(self, request, view) -> bool:
        membership = resolve_membership(request, view)
        return membership.role in ALL_ROLES


class IsOrgAdmin(IsOrgMember):
    def has_permission(self, request, view) -> bool:
        membership = resolve_membership(request, view)
        if membership.role not in ADMIN_ROLES:
            raise PermissionDenied("Administrator role required")
        return True


class IsOrgWriter(IsOrgMember):
    """Members who may mutate resources (viewers are read-only)."""

    def has_permission(self, request, view) -> bool:
        membership = resolve_membership(request, view)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        if membership.role == "viewer":
            raise PermissionDenied("Viewer role is read-only")
        return True


class IsDeviceAuthenticated(BasePermission):
    """Local runner sockets authenticate as a device, not a user."""

    def has_permission(self, request, view) -> bool:
        return getattr(request, "device", None) is not None
