"""Device pairing: mint a single-use code, exchange it for a device identity.

The code is the only secret a fresh runner holds, so it is short-lived, single
use, attempt-limited, and stored only as a hash.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from execution.models import LocalRunnerDevice, PairingCode
from execution.tokens import mint_runner_token

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
# No 0/O/1/I: these codes get read off a screen and typed by a human.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class PairingError(ValueError):
    """Anything that should become a 400 with a safe, non-enumerating message."""


def hash_code(code: str) -> str:
    normalized = (code or "").strip().replace("-", "").replace(" ", "").upper()
    return hashlib.sha256(normalized.encode()).hexdigest()


def _format(raw: str) -> str:
    return f"{raw[:4]}-{raw[4:]}"


def mint_code(organization, profile) -> tuple[str, PairingCode]:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
    code = PairingCode.objects.create(
        organization=organization,
        created_by=profile,
        code_hash=hash_code(raw),
        expires_at=timezone.now() + CODE_TTL,
    )
    return _format(raw), code


def claim_code(
    *,
    code: str,
    fingerprint: str,
    name: str,
    os_name: str = "",
    arch: str = "",
    workspace_roots: list[str] | None = None,
) -> tuple[LocalRunnerDevice, str]:
    """Exchange a pairing code for a device row and a short-lived token."""
    if not code or not fingerprint:
        raise PairingError("code and fingerprint are required")
    if not 16 <= len(fingerprint) <= 64:
        raise PairingError("fingerprint must be 16-64 characters")
    if not name.strip():
        raise PairingError("device name is required")

    digest = hash_code(code)

    with transaction.atomic():
        record = (
            PairingCode.objects.select_for_update()
            .filter(code_hash=digest)
            .first()
        )
        # Deliberately identical message for unknown / used / expired codes so the
        # endpoint cannot be used to confirm that a code once existed.
        if record is None:
            raise PairingError("pairing code is invalid or expired")
        if record.claimed_at is not None:
            raise PairingError("pairing code is invalid or expired")
        if record.expires_at <= timezone.now():
            raise PairingError("pairing code is invalid or expired")
        if record.attempts >= MAX_ATTEMPTS:
            raise PairingError("pairing code is invalid or expired")

        record.attempts += 1

        device, _created = LocalRunnerDevice.objects.update_or_create(
            organization=record.organization,
            fingerprint=fingerprint,
            defaults={
                "name": name.strip()[:120],
                "os": os_name[:40],
                "arch": arch[:40],
                "paired_by": record.created_by,
                "revoked_at": None,
                "workspace_roots": [r[:400] for r in (workspace_roots or [])][:20],
            },
        )

        record.claimed_at = timezone.now()
        record.claimed_by_device = device
        record.save(update_fields=["attempts", "claimed_at", "claimed_by_device"])

    return device, mint_runner_token(device)


def revoke(device: LocalRunnerDevice) -> None:
    device.revoked_at = timezone.now()
    device.save(update_fields=["revoked_at"])
