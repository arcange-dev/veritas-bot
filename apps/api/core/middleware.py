"""Request correlation + defence-in-depth redaction."""
from __future__ import annotations

import logging
import re
import uuid

logger = logging.getLogger(__name__)

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),
    re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]


def redact(value: str) -> str:
    if not isinstance(value, str):
        return value
    for pattern in SECRET_PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value


class RequestContextMiddleware:
    """Attach a request id and make it available to the log formatter."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-Id", "")
        request.request_id = incoming if re.fullmatch(r"[A-Za-z0-9\-]{8,64}", incoming) else uuid.uuid4().hex
        response = self.get_response(request)
        response["X-Request-Id"] = request.request_id
        return response


class SecretRedactionMiddleware:
    """Belt and braces: scrub the response body for anything key-shaped.

    A credential should never reach a response, so if this filter ever fires it
    means a bug upstream. It logs loudly and still scrubs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        ctype = response.get("Content-Type", "")
        if ctype.startswith("application/json") and getattr(response, "content", None):
            try:
                body = response.content.decode("utf-8", errors="ignore")
            except Exception:
                return response
            scrubbed = redact(body)
            if scrubbed != body:
                logger.error(
                    "credential-shaped value in response body; upstream bug",
                    extra={"request_id": getattr(request, "request_id", "")},
                )
                response.content = scrubbed.encode("utf-8")
        return response
