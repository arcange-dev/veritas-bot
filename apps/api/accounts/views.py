"""The signed-in person: who they are and which workspaces they belong to.

These routes are per-user, not per-organization, so there is no tenant to bind. They
use `profile_context` (identity only), and the policies added in core 0003/0004 let a
person read their own memberships and the organizations those point at, nothing else.
"""
from __future__ import annotations

import re
import uuid

from django.db import IntegrityError, transaction
from django.utils.text import slugify
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.rls import _set, profile_context
from identity.models import Membership, MembershipRole, Organization

SLUG_ATTEMPTS = 6


def _memberships(profile):
    return list(
        Membership.objects.filter(profile_id=profile.pk, is_active=True)
        .values("organization_id", "role", "organization__name", "organization__slug", "organization__plan")
        .order_by("created_at")
    )


def _payload(profile) -> dict:
    return {
        "profile": {
            "id": str(profile.pk),
            "email": profile.email,
            "display_name": profile.display_name,
            "avatar_url": profile.avatar_url,
            "is_platform_admin": bool(profile.is_platform_admin),
            "onboarded": profile.onboarded_at is not None,
        },
        "organizations": [
            {
                "id": str(m["organization_id"]),
                "name": m["organization__name"],
                "slug": m["organization__slug"],
                "plan": m["organization__plan"],
                "role": m["role"],
            }
            for m in _memberships(profile)
        ],
    }


class MeView(APIView):
    """GET /api/v1/me/"""

    def get(self, request):
        with profile_context(profile=request.user):
            return Response(_payload(request.user))


class CreateOrganizationSerializer(serializers.Serializer):
    name = serializers.CharField(min_length=2, max_length=120, trim_whitespace=True)


def _unique_slug(name: str) -> str:
    base = (slugify(name) or "workspace")[:48].strip("-") or "workspace"
    for i in range(SLUG_ATTEMPTS):
        candidate = base if i == 0 else f"{base}-{uuid.uuid4().hex[:6]}"
        if not Organization.objects.filter(slug=candidate).exists():
            return candidate
    return f"{base}-{uuid.uuid4().hex[:12]}"


class MyOrganizationsView(APIView):
    """POST /api/v1/me/organizations/  create a workspace and become its owner."""

    def post(self, request):
        ser = CreateOrganizationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        name = re.sub(r"\s+", " ", ser.validated_data["name"]).strip()
        profile = request.user

        # A user may create a handful of workspaces, not unbounded ones.
        with profile_context(profile=profile):
            if Membership.objects.filter(profile_id=profile.pk, role=MembershipRole.OWNER, is_active=True).count() >= 5:
                return Response({"code": "workspace_limit", "detail": "You can own at most 5 workspaces."},
                                status=status.HTTP_409_CONFLICT)

        org_id = uuid.uuid4()
        for _ in range(SLUG_ATTEMPTS):
            try:
                with transaction.atomic():
                    # The org policy only admits a row whose id is the bound org, so bind the
                    # id we are about to insert. The owner membership is written in the same
                    # transaction: either both exist or neither does.
                    _set(str(profile.pk), str(org_id))
                    org = Organization.objects.create(
                        id=org_id, name=name, slug=_unique_slug(name), created_by=profile)
                    Membership.objects.create(organization=org, profile=profile, role=MembershipRole.OWNER)
                break
            except IntegrityError:
                continue                       # slug raced with another creator; pick a new one
        else:
            return Response({"code": "slug_conflict", "detail": "Could not reserve a workspace address. Try again."},
                            status=status.HTTP_409_CONFLICT)

        with profile_context(profile=profile):
            return Response(_payload(profile), status=status.HTTP_201_CREATED)
