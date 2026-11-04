"""GitHub App plumbing: configuration probing and webhook signature checks.

Nothing here talks to GitHub. There is no GitHub App registered for this
deployment and no API client, so this module deliberately stops at the two
things that can be done correctly without one:

* decide, from settings, whether an App *could* be installed (``configured``),
* verify that a webhook really came from GitHub (HMAC-SHA256 over the raw body).

Every settings read uses ``getattr(settings, name, "")`` so the whole feature
works on a server where none of these variables are set, which is the current
state. Nothing here logs, returns or formats a secret.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import urlencode

from django.conf import settings

SIGNATURE_HEADER = "X-Hub-Signature-256"
DELIVERY_HEADER = "X-GitHub-Delivery"
EVENT_HEADER = "X-GitHub-Event"

# GitHub's delivery ids are UUID-shaped. Bounding the alphabet keeps a hostile
# client from using this column as a dumping ground for arbitrary text.
_DELIVERY_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
# A prefix plus 64 lowercase hex characters. Validated before compare_digest,
# which raises TypeError on non-ASCII input.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^sha256=([0-9a-fA-F]{64})$")

SUPPORTED_EVENTS = frozenset({"ping", "installation", "push", "pull_request"})


def app_id() -> str:
    return str(getattr(settings, "GITHUB_APP_ID", "") or "").strip()


def app_private_key() -> str:
    """The App private key, only ever tested for presence — never logged."""
    return str(getattr(settings, "GITHUB_APP_PRIVATE_KEY", "") or "").strip()


def app_slug() -> str:
    return str(getattr(settings, "GITHUB_APP_SLUG", "") or "").strip()


def webhook_secret() -> str:
    return str(getattr(settings, "GITHUB_WEBHOOK_SECRET", "") or "").strip()


def is_configured() -> bool:
    """True only when this server could actually act as a GitHub App.

    Both the App id and its private key are required: an id alone can identify
    an installation but cannot mint anything, and a key alone belongs to no app.
    """
    return bool(app_id() and app_private_key())


def is_webhook_configured() -> bool:
    return bool(webhook_secret())


def installation_url(state: str = "") -> str:
    """Where a user installs the App on their account or organization.

    GitHub only publishes install links by App slug, so a server with an id and
    key but no slug cannot produce a working link; ``installations/new`` on a
    slugless app would 404 for the user. The caller turns that into an honest
    409 instead.
    """
    slug = app_slug()
    if not slug:
        return ""
    url = f"https://github.com/apps/{slug}/installations/new"
    if state:
        url = f"{url}?{urlencode({'state': state})}"
    return url


def verify_signature(*, payload: bytes, signature_header: str | None, secret: str) -> bool:
    """Constant-time check of ``X-Hub-Signature-256`` against the raw body.

    The body must be the exact bytes GitHub signed. Re-serialising parsed JSON
    would change whitespace and key order and break a valid signature, so the
    view passes ``request.body`` straight through.

    Returns False (never raises) for a missing secret, a missing or malformed
    header, or a mismatch: the caller answers 401 and learns nothing about
    which of those it was.
    """
    if not secret or not signature_header:
        return False
    match = _SIGNATURE_RE.match(signature_header.strip())
    if match is None:
        return False
    provided = match.group(1).lower()
    if not _SHA256_RE.match(provided):
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    # compare_digest is length-constant AND content-constant, unlike ``==``
    # which short-circuits on the first differing byte and leaks a prefix.
    return hmac.compare_digest(expected, provided)


def payload_digest(payload: bytes) -> str:
    """SHA-256 of the body: proves what arrived without storing someone's code."""
    return hashlib.sha256(payload).hexdigest()


def valid_delivery_id(value: str | None) -> str:
    if not value or not _DELIVERY_RE.match(value):
        return ""
    return value


def sign_test_payload(payload: bytes, secret: str) -> str:
    """Produce a real signature so the test-delivery path exercises verification."""
    return "sha256=" + hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
