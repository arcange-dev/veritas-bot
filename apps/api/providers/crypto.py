"""The only module allowed to encrypt or decrypt a provider credential.

Rules enforced here:
  * Fernet (AES-128-CBC + HMAC-SHA256) via MultiFernet, so keys can rotate.
  * The key id is stored alongside the token so decryption picks the right key.
  * Nothing in this module logs, prints, or includes the token in an exception.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from core.errors import CredentialDecryptionError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KeyedFernet:
    key_id: str
    fernet: Fernet


def _parse_keys() -> list[KeyedFernet]:
    raw = list(getattr(settings, "BYOK_ENCRYPTION_KEYS", []) or [])
    if not raw:
        raise ImproperlyConfigured(
            "BYOK_ENCRYPTION_KEYS is empty. Generate one with "
            "cryptography.fernet.Fernet.generate_key() and set it before serving traffic."
        )
    parsed: list[KeyedFernet] = []
    for entry in raw:
        if ":" in entry:
            key_id, key = entry.split(":", 1)
        else:
            key_id, key = getattr(settings, "BYOK_ACTIVE_KEY_ID", "k1"), entry
        try:
            parsed.append(KeyedFernet(key_id=key_id, fernet=Fernet(key.encode())))
        except Exception as exc:
            raise ImproperlyConfigured(
                f"BYOK key {key_id} is not a valid Fernet key"
            ) from exc
    return parsed


def active_key_id() -> str:
    return _parse_keys()[0].key_id


def encrypt_secret(api_key: str, base_url: str = "") -> tuple[bytes, str]:
    """Encrypt a credential. Returns (token_bytes, key_id) for storage."""
    if not api_key or len(api_key) < 4:
        raise ValueError("Refusing to store an empty or implausibly short key")
    payload = json.dumps({"api_key": api_key, "base_url": base_url}).encode()
    keys = _parse_keys()
    token = MultiFernet([k.fernet for k in keys]).encrypt(payload)
    return token, keys[0].key_id


def decrypt_secret(token: bytes | memoryview, key_id: str = "") -> dict:
    """Decrypt to {'api_key': ..., 'base_url': ...}.

    Callers must not serialize, log, or forward the result. If you are writing
    a serializer field for this, you are doing it wrong.
    """
    if isinstance(token, memoryview):
        token = token.tobytes()
    keys = _parse_keys()
    ordered = [k for k in keys if k.key_id == key_id] + [k for k in keys if k.key_id != key_id]
    try:
        plaintext = MultiFernet([k.fernet for k in ordered]).decrypt(token)
    except (InvalidToken, ValueError) as exc:
        # Never include the token or the exception's bytes in the message.
        logger.warning("credential decryption failed for key_id=%s", key_id or "unknown")
        raise CredentialDecryptionError(
            "This credential cannot be decrypted. Re-add it in provider settings."
        ) from exc
    data = json.loads(plaintext)
    return {"api_key": data.get("api_key", ""), "base_url": data.get("base_url", "")}


def reencrypt(token: bytes, key_id: str = "") -> tuple[bytes, str]:
    """Used by the rotation task: decrypt with any key, encrypt with the newest."""
    data = decrypt_secret(token, key_id)
    return encrypt_secret(data["api_key"], data["base_url"])
