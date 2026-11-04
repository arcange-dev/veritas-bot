"""Credential encryption is the highest-consequence module in the product."""
import pytest
from cryptography.fernet import Fernet
from django.test import override_settings

from core.errors import CredentialDecryptionError
from providers.crypto import decrypt_secret, encrypt_secret, reencrypt

KEY_1 = "k1:" + Fernet.generate_key().decode()


def test_roundtrip_returns_the_original_key():
    from providers.crypto import active_key_id

    token, key_id = encrypt_secret("sk-test-abcdef123456", "https://api.example.com")
    assert key_id == active_key_id()
    assert isinstance(token, bytes)
    out = decrypt_secret(token, key_id)
    assert out["api_key"] == "sk-test-abcdef123456"
    assert out["base_url"] == "https://api.example.com"


def test_ciphertext_does_not_contain_the_plaintext():
    token, _ = encrypt_secret("sk-test-abcdef123456")
    assert b"sk-test-abcdef123456" not in token


def test_tampered_token_raises_without_leaking_material():
    token, key_id = encrypt_secret("sk-test-abcdef123456")
    tampered = bytearray(token)
    tampered[-1] ^= 0xFF
    with pytest.raises(CredentialDecryptionError) as exc:
        decrypt_secret(bytes(tampered), key_id)
    assert "sk-test" not in str(exc.value)


def test_empty_key_is_refused():
    with pytest.raises(ValueError):
        encrypt_secret("")


def test_rotation_decrypts_with_old_key_and_reencrypts_with_new():
    old = "k1:" + Fernet.generate_key().decode()
    new = "k2:" + Fernet.generate_key().decode()
    with override_settings(BYOK_ENCRYPTION_KEYS=[old], BYOK_ACTIVE_KEY_ID="k1"):
        token, kid = encrypt_secret("sk-rotate-me-1234")
        assert kid == "k1"

    # New key first: decryption still works via MultiFernet, encryption uses k2.
    with override_settings(BYOK_ENCRYPTION_KEYS=[new, old], BYOK_ACTIVE_KEY_ID="k2"):
        assert decrypt_secret(token, kid)["api_key"] == "sk-rotate-me-1234"
        rotated, new_kid = reencrypt(token, kid)
        assert new_kid == "k2"
        assert decrypt_secret(rotated, new_kid)["api_key"] == "sk-rotate-me-1234"
        # The old key is now unnecessary for this row.
    with override_settings(BYOK_ENCRYPTION_KEYS=[new], BYOK_ACTIVE_KEY_ID="k2"):
        assert decrypt_secret(rotated, "k2")["api_key"] == "sk-rotate-me-1234"


def test_credential_repr_never_contains_ciphertext(org, profile):
    from providers.models import ProviderCredential

    token, kid = encrypt_secret("sk-repr-check-9999")
    cred = ProviderCredential(
        organization=org, provider="openai", secret_encrypted=token,
        key_id=kid, last4="9999", created_by=profile,
    )
    assert "sk-repr-check" not in repr(cred)
    assert "9999" in repr(cred)
