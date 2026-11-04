"""Runner tokens are device-bound and short lived."""
import time

import jwt
import pytest
from django.conf import settings
from rest_framework.exceptions import AuthenticationFailed

from execution.models import LocalRunnerDevice
from execution.tokens import mint_runner_token, verify_runner_token


@pytest.fixture
def device(org, profile):
    return LocalRunnerDevice.objects.create(
        organization=org, name="workstation", fingerprint="abc123",
        paired_by=profile, os="linux", arch="x86_64",
    )


def test_minted_token_verifies_for_its_device(device):
    token = mint_runner_token(device)
    assert verify_runner_token(token, str(device.id)).id == device.id


def test_token_audience_and_ttl(device):
    claims = jwt.decode(mint_runner_token(device), settings.RUNNER_JWT_KEY,
                        algorithms=["HS256"], audience="runner")
    assert claims["aud"] == "runner"
    assert claims["exp"] - claims["iat"] == 15 * 60
    assert claims["scope"] == ["exec", "fs", "git", "stream"]


def test_token_cannot_be_used_for_another_device(device, org, profile):
    other = LocalRunnerDevice.objects.create(
        organization=org, name="other", fingerprint="zzz", paired_by=profile
    )
    with pytest.raises(AuthenticationFailed):
        verify_runner_token(mint_runner_token(device), str(other.id))


def test_revoked_device_is_rejected(device):
    from django.utils import timezone

    token = mint_runner_token(device)
    device.revoked_at = timezone.now()
    device.save(update_fields=["revoked_at"])
    with pytest.raises(AuthenticationFailed):
        verify_runner_token(token, str(device.id))


def test_expired_token_is_rejected(device):
    now = int(time.time()) - 3600
    expired = jwt.encode(
        {"sub": str(device.id), "aud": "runner", "exp": now, "iat": now - 900},
        settings.RUNNER_JWT_KEY, algorithm="HS256",
    )
    with pytest.raises(AuthenticationFailed):
        verify_runner_token(expired, str(device.id))
