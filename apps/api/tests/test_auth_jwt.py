"""Supabase JWT verification through the real authentication class.

Nothing here uses force_authenticate: tokens are signed, sent as a header, and
verified by SupabaseJWTAuthentication, the same path production requests take.
"""
from __future__ import annotations

import base64
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from rest_framework.test import APIClient

from identity import authentication
from identity.models import Membership, MembershipRole, Organization, Profile

SECRET = "test-secret-that-is-comfortably-longer-than-32-bytes"
SUB = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def configured(settings):
    settings.SUPABASE_JWT_SECRET = SECRET
    settings.SUPABASE_JWT_AUDIENCE = "authenticated"
    authentication._jwks_cache.clear() if hasattr(authentication, "_jwks_cache") else None


def token(*, secret=SECRET, alg="HS256", sub=SUB, aud="authenticated", exp=3600,
          headers=None, **claims):
    payload = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp,
               "email": "user@example.com", **claims}
    if sub is None:
        payload.pop("sub")
    return jwt.encode(payload, secret, algorithm=alg, headers=headers)


def call(bearer=None, raw_header=None):
    client = APIClient()
    kwargs = {}
    if raw_header is not None:
        kwargs["HTTP_AUTHORIZATION"] = raw_header
    elif bearer is not None:
        kwargs["HTTP_AUTHORIZATION"] = f"Bearer {bearer}"
    return client.get("/api/v1/orgs/11111111-1111-4111-8111-111111111111/projects/", **kwargs)


@pytest.mark.django_db
def test_a_valid_token_authenticates_and_creates_the_profile_once():
    assert not Profile.objects.filter(supabase_user_id=SUB).exists()
    assert call(token()).status_code == 404            # authenticated; not a member of that org
    assert call(token()).status_code == 404
    assert Profile.objects.filter(supabase_user_id=SUB).count() == 1


@pytest.mark.django_db
def test_a_member_can_use_a_real_token_end_to_end():
    profile = Profile.objects.create(supabase_user_id=SUB, email="user@example.com")
    org = Organization.objects.create(name="Acme", slug="acme", created_by=profile)
    Membership.objects.create(organization=org, profile=profile, role=MembershipRole.OWNER)
    client = APIClient()
    resp = client.get(f"/api/v1/orgs/{org.id}/projects/",
                      HTTP_AUTHORIZATION=f"Bearer {token()}")
    assert resp.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("header", [None, "", "Bearer", "Bearer a b", "Basic abc", "bearer"])
def test_missing_or_malformed_headers_are_401(header):
    resp = call(raw_header=header)
    assert resp.status_code == 401, header


@pytest.mark.django_db
def test_expired_token_is_401():
    assert call(token(exp=-10)).status_code == 401


@pytest.mark.django_db
def test_wrong_signature_is_401():
    assert call(token(secret="x" * 40)).status_code == 401


@pytest.mark.django_db
def test_wrong_audience_is_401():
    assert call(token(aud="some-other-service")).status_code == 401


@pytest.mark.django_db
def test_missing_subject_is_401():
    assert call(token(sub=None)).status_code == 401


@pytest.mark.django_db
def test_missing_expiry_is_401():
    no_exp = jwt.encode({"sub": SUB, "aud": "authenticated"}, SECRET, algorithm="HS256")
    assert call(no_exp).status_code == 401


@pytest.mark.django_db
def test_alg_none_is_rejected():
    """The oldest JWT attack: an unsigned token claiming alg=none."""
    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    forged = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': SUB, 'aud': 'authenticated', 'exp': int(time.time()) + 3600})}."
    assert call(forged).status_code == 401
    assert not Profile.objects.filter(supabase_user_id=SUB).exists()


@pytest.mark.django_db
def test_algorithm_confusion_with_a_public_key_is_rejected():
    """HS256 token whose HMAC secret is an RSA *public key*.

    PyJWT's encoder refuses to build this, but a real attacker has no such
    guard, so the token is assembled by hand. If the verifier trusted the
    header's alg and used the published public key as an HMAC secret, anyone
    holding that (public) key could mint valid tokens for any user.
    """
    import hashlib
    import hmac

    from cryptography.hazmat.primitives import serialization

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    signing_input = (
        b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + b"." +
        b64(json.dumps({"sub": SUB, "aud": "authenticated",
                        "exp": int(time.time()) + 3600}).encode())
    )
    signature = hmac.new(public_pem, signing_input, hashlib.sha256).digest()
    forged = (signing_input + b"." + b64(signature)).decode()

    assert call(forged).status_code == 401
    assert not Profile.objects.filter(supabase_user_id=SUB).exists()


@pytest.mark.django_db
def test_unsupported_algorithms_are_rejected():
    for alg in ("HS512", "HS384"):
        assert call(token(alg=alg)).status_code == 401, alg


@pytest.mark.django_db
def test_asymmetric_token_without_a_key_id_is_rejected():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode({"sub": SUB, "aud": "authenticated", "exp": int(time.time()) + 3600},
                        private, algorithm="RS256")
    assert call(forged).status_code == 401


@pytest.mark.django_db
def test_asymmetric_token_signed_by_an_unknown_key_is_rejected(monkeypatch):
    trusted = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(trusted.public_key()))
    jwk.update({"kid": "trusted-1", "alg": "RS256", "use": "sig"})
    monkeypatch.setattr(authentication, "_fetch_jwks", lambda force=False: [jwk])

    good = jwt.encode({"sub": SUB, "aud": "authenticated", "exp": int(time.time()) + 3600},
                      trusted, algorithm="RS256", headers={"kid": "trusted-1"})
    forged = jwt.encode({"sub": SUB, "aud": "authenticated", "exp": int(time.time()) + 3600},
                        attacker, algorithm="RS256", headers={"kid": "trusted-1"})
    unknown_kid = jwt.encode({"sub": SUB, "aud": "authenticated", "exp": int(time.time()) + 3600},
                             trusted, algorithm="RS256", headers={"kid": "nope"})

    assert call(good).status_code == 404          # authenticated (not an org member)
    assert call(forged).status_code == 401        # right kid, wrong key
    assert call(unknown_kid).status_code == 401   # kid not in the key set


@pytest.mark.django_db
def test_an_unconfigured_secret_fails_closed():
    from django.test import override_settings

    with override_settings(SUPABASE_JWT_SECRET=""):
        assert call(token()).status_code == 401


@pytest.mark.django_db
def test_error_responses_do_not_leak_internals():
    body = call(token(secret="y" * 40)).json()
    text = json.dumps(body).lower()
    assert "traceback" not in text and SECRET not in text
    assert "signature" not in text or "invalid" in text      # generic message only
