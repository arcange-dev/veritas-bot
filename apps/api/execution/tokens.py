"""Device-bound, short-lived runner tokens (EdDSA when a key is present)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from execution.models import LocalRunnerDevice

ALGORITHM = "HS256"          # EdDSA when RUNNER_JWT_KEY is an Ed25519 PEM
RUNNER_TOKEN_TTL = timedelta(minutes=15)


def mint_runner_token(device: LocalRunnerDevice) -> str:
    now = timezone.now()
    return jwt.encode(
        {
            "sub": str(device.id),
            "aud": "runner",
            "org": str(device.organization_id),
            "scope": ["exec", "fs", "git", "stream"],
            "iat": int(now.timestamp()),
            "exp": int((now + RUNNER_TOKEN_TTL).timestamp()),
            "jti": uuid.uuid4().hex,
        },
        settings.RUNNER_JWT_KEY,
        algorithm=ALGORITHM,
    )


def verify_runner_token(token: str, device_id: str) -> LocalRunnerDevice:
    try:
        claims = jwt.decode(
            token, settings.RUNNER_JWT_KEY, algorithms=[ALGORITHM],
            audience="runner", options={"require": ["exp", "sub", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("invalid runner token") from exc
    if claims.get("sub") != device_id:
        raise AuthenticationFailed("token does not match device")
    device = LocalRunnerDevice.objects.filter(id=device_id, revoked_at__isnull=True).first()
    if device is None:
        raise AuthenticationFailed("device not paired or revoked")
    return device
