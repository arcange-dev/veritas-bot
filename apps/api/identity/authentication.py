"""Supabase JWT verification.

Never trust an unverified token. Supports the two shapes Supabase issues:
  * HS256 signed with the project JWT secret
  * RS256/ES256 signed with a rotated JWKS key (preferred, new projects)

The JWKS response is cached for JWKS_CACHE_SECONDS and refetched once on an
unknown `kid`, then we fail closed.
"""
from __future__ import annotations

import logging
import threading
import time

import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.rls import login_context

from .models import Profile

logger = logging.getLogger(__name__)

_jwks_cache: dict[str, object] = {"keys": None, "fetched_at": 0.0}
_jwks_lock = threading.Lock()


def _fetch_jwks(force: bool = False) -> list[dict]:
    if not settings.SUPABASE_JWKS_URL:
        raise ImproperlyConfigured("SUPABASE_JWKS_URL is not set")
    now = time.monotonic()
    with _jwks_lock:
        fresh = _jwks_cache["keys"] is not None and (
            now - float(_jwks_cache["fetched_at"]) < settings.JWT_JWKS_CACHE_SECONDS
        )
        if fresh and not force:
            return list(_jwks_cache["keys"])  # type: ignore[arg-type]
        import httpx

        try:
            resp = httpx.get(settings.SUPABASE_JWKS_URL, timeout=5.0)
            resp.raise_for_status()
            keys = resp.json().get("keys", [])
        except Exception as exc:  # network / parse
            logger.error("failed to fetch supabase JWKS: %s", type(exc).__name__)
            raise AuthenticationFailed("Authentication temporarily unavailable") from exc
        _jwks_cache["keys"] = keys
        _jwks_cache["fetched_at"] = now
        return keys


def _signing_key_for(token: str):
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")
    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise AuthenticationFailed("JWT secret not configured")
        return settings.SUPABASE_JWT_SECRET
    kid = header.get("kid")
    if not kid:
        raise AuthenticationFailed("Token missing key id")
    keys = _fetch_jwks()
    match = next((k for k in keys if k.get("kid") == kid), None)
    if match is None:
        keys = _fetch_jwks(force=True)
        match = next((k for k in keys if k.get("kid") == kid), None)
    if match is None:
        raise AuthenticationFailed("Unknown signing key")
    return jwt.PyJWK(match).key


def decode_supabase_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg", "")
        if alg not in {"HS256", "RS256", "ES256"}:
            raise AuthenticationFailed("Unsupported token algorithm")
        return jwt.decode(
            token,
            _signing_key_for(token),
            algorithms=[alg],
            audience=settings.SUPABASE_JWT_AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
        )
    except AuthenticationFailed:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("Invalid token") from exc


class SupabaseJWTAuthentication(BaseAuthentication):
    """Maps a verified Supabase token to a Profile, creating it on first sight."""

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("Malformed Authorization header")

        try:
            token = parts[1].decode()
        except UnicodeDecodeError as exc:
            raise AuthenticationFailed("Malformed token") from exc

        claims = decode_supabase_token(token)
        sub = claims.get("sub")
        email = claims.get("email", "")
        if not sub:
            raise AuthenticationFailed("Token missing subject")

        # The token is verified, so `sub` is trustworthy. Bind it as the login subject so the
        # profile can be found or created under row-level security (core migration 0005).
        try:
            with login_context(subject=sub):
                profile, _ = Profile.objects.get_or_create(
                    supabase_user_id=sub,
                    defaults={
                        "email": email,
                        "display_name": str((claims.get("user_metadata") or {}).get("full_name", ""))[:120],
                    },
                )
                if not profile.email and email:
                    profile.email = email
                    profile.save(update_fields=["email"])
        except (ValueError, TypeError) as exc:      # a subject that is not a UUID
            raise AuthenticationFailed("Token subject is not valid") from exc

        request.jwt_claims = claims
        return (profile, token)

    def authenticate_header(self, request) -> str:
        return 'Bearer realm="superagent"'
