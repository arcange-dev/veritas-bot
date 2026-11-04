"""Pairing a device: the one unauthenticated write path in the API."""
from __future__ import annotations

import pytest
from rest_framework.exceptions import AuthenticationFailed

from execution.models import LocalRunnerDevice, PairingCode
from execution.pairing import claim_code, mint_code
from execution.tokens import verify_runner_token

pytestmark = pytest.mark.django_db

FINGERPRINT = "ab12cd34ef56ab78cd90ef12ab34cd56"


def _claim(client, **overrides):
    payload = {
        "code": overrides.pop("code", ""),
        "fingerprint": FINGERPRINT,
        "name": "Arcange laptop",
        "os": "linux",
        "arch": "x86_64",
        "workspace_roots": ["/home/dev/projects"],
    }
    payload.update(overrides)
    return client.post("/api/v1/runners/claim/", payload, format="json")


def test_admin_mints_a_code_that_a_runner_can_claim(api, org, profile):
    from rest_framework.test import APIClient

    minted = api.post(f"/api/v1/orgs/{org.id}/runners/pairing-codes/")
    assert minted.status_code == 201
    code = minted.data["code"]
    assert len(code) == 9 and code[4] == "-"

    anon = APIClient()
    claimed = _claim(anon, code=code)
    assert claimed.status_code == 201
    assert claimed.data["device_id"]
    assert claimed.data["token"]

    device = LocalRunnerDevice.objects.get(id=claimed.data["device_id"])
    assert device.organization_id == org.id
    assert device.workspace_roots == ["/home/dev/projects"]
    # The returned token authenticates that device and only that device.
    assert verify_runner_token(claimed.data["token"], str(device.id)).id == device.id


def test_a_code_cannot_be_claimed_twice(api, org):
    from rest_framework.test import APIClient

    code = api.post(f"/api/v1/orgs/{org.id}/runners/pairing-codes/").data["code"]
    anon = APIClient()
    assert _claim(anon, code=code).status_code == 201
    second = _claim(anon, code=code)
    assert second.status_code == 400
    assert second.data["error"]["code"] == "invalid_pairing_code"


def test_expired_code_is_refused(org, profile):
    from django.utils import timezone
    from datetime import timedelta

    code, record = mint_code(org, profile)
    PairingCode.objects.filter(id=record.id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )
    with pytest.raises(Exception) as exc:
        claim_code(code=code, fingerprint=FINGERPRINT, name="stale")
    assert "invalid or expired" in str(exc.value)


def test_unknown_code_looks_identical_to_a_used_one():
    """No enumeration: every failure message is the same."""
    with pytest.raises(Exception) as exc:
        claim_code(code="ZZZZ-ZZZZ", fingerprint=FINGERPRINT, name="x")
    assert "invalid or expired" in str(exc.value)


def test_short_fingerprint_is_rejected(api, org):
    from rest_framework.test import APIClient

    code = api.post(f"/api/v1/orgs/{org.id}/runners/pairing-codes/").data["code"]
    assert _claim(APIClient(), code=code, fingerprint="short").status_code == 400


def test_non_admin_member_cannot_mint_a_code(api, org, profile):
    from identity.models import Membership, MembershipRole, Profile
    from rest_framework.test import APIClient

    viewer = Profile.objects.create(
        supabase_user_id="33333333-3333-4333-8333-333333333333", email="v@example.com"
    )
    Membership.objects.create(
        organization=org, profile=viewer, role=MembershipRole.VIEWER
    )
    client = APIClient()
    client.force_authenticate(user=viewer)
    assert client.post(f"/api/v1/orgs/{org.id}/runners/pairing-codes/").status_code == 403


def test_devices_are_invisible_to_another_tenant(api, org, other_org, profile):
    from rest_framework.test import APIClient

    platform_owned = LocalRunnerDevice.objects.create(
        organization=other_org, name="Their mac", fingerprint="f" * 32,
        paired_by=other_org.created_by,
    )
    # Scoped list on our own org must not include it.
    mine = api.get(f"/api/v1/orgs/{org.id}/runners/")
    assert mine.status_code == 200
    items = mine.data["results"] if isinstance(mine.data, dict) else mine.data
    assert items == [], "another tenant's device leaked into the scoped list"

    # And it is not reachable by id through our org's route.
    assert api.get(f"/api/v1/orgs/{org.id}/runners/{platform_owned.id}/").status_code == 404


def test_revoking_a_device_kills_its_token(api, org, profile):
    device = LocalRunnerDevice.objects.create(
        organization=org, name="Laptop", fingerprint="c" * 32, paired_by=profile
    )
    from execution.pairing import revoke
    from execution.tokens import mint_runner_token

    token = mint_runner_token(device)
    assert verify_runner_token(token, str(device.id)).id == device.id

    response = api.post(f"/api/v1/orgs/{org.id}/runners/{device.id}/revoke/")
    assert response.status_code == 200
    assert response.data["revoked_at"]

    with pytest.raises(AuthenticationFailed):
        verify_runner_token(token, str(device.id))
