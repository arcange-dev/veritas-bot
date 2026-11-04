from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from identity.models import Membership, MembershipRole, Organization, Profile


@pytest.fixture
def profile(db) -> Profile:
    return Profile.objects.create(
        supabase_user_id="11111111-1111-4111-8111-111111111111",
        email="dev@example.com",
        display_name="Dev",
    )


@pytest.fixture
def org(db, profile) -> Organization:
    organization = Organization.objects.create(
        name="Acme", slug="acme", created_by=profile
    )
    Membership.objects.create(
        organization=organization, profile=profile, role=MembershipRole.OWNER
    )
    return organization


@pytest.fixture
def other_org(db) -> Organization:
    outsider = Profile.objects.create(
        supabase_user_id="22222222-2222-4222-8222-222222222222",
        email="other@example.com",
    )
    organization = Organization.objects.create(
        name="Globex", slug="globex", created_by=outsider
    )
    Membership.objects.create(
        organization=organization, profile=outsider, role=MembershipRole.OWNER
    )
    return organization


@pytest.fixture
def api(profile) -> APIClient:
    client = APIClient()
    # Supabase JWTs are covered by test_auth_jwt; here we exercise authorization.
    client.force_authenticate(user=profile)
    return client
