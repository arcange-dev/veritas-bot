"""Uniform error envelope. `detail` never contains internals."""
from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler

logger = logging.getLogger(__name__)

SAFE_MESSAGES = {
    status.HTTP_400_BAD_REQUEST: "Invalid request",
    status.HTTP_401_UNAUTHORIZED: "Authentication required",
    status.HTTP_403_FORBIDDEN: "Not permitted",
    status.HTTP_404_NOT_FOUND: "Not found",
    status.HTTP_429_TOO_MANY_REQUESTS: "Too many requests",
}


class DomainError(Exception):
    """Base for expected business failures. Safe to show the user."""

    code = "domain_error"
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, detail: str = "", *, code: str | None = None):
        self.detail = detail or self.code
        if code:
            self.code = code
        super().__init__(self.detail)


class SpendCapExceeded(DomainError):
    code = "spend_cap_exceeded"
    status_code = status.HTTP_402_PAYMENT_REQUIRED


class NoUsableModel(DomainError):
    code = "no_usable_model"
    status_code = status.HTTP_409_CONFLICT


class InvalidState(DomainError):
    """The requested action is not valid for the resource's current state."""

    code = "invalid_state"
    status_code = status.HTTP_409_CONFLICT


class CredentialDecryptionError(DomainError):
    code = "credential_unreadable"
    status_code = status.HTTP_409_CONFLICT


class PathOutsideWorkspace(DomainError):
    code = "path_outside_workspace"
    status_code = status.HTTP_400_BAD_REQUEST


class ApprovalRequired(DomainError):
    code = "approval_required"
    status_code = status.HTTP_409_CONFLICT


def _request_id(request) -> str:
    return getattr(request, "request_id", "") or ""


def exception_handler(exc, context):
    request = context.get("request")
    rid = _request_id(request) if request else ""

    if isinstance(exc, DomainError):
        return Response(
            {"code": exc.code, "detail": exc.detail, "request_id": rid},
            status=exc.status_code,
        )

    response = drf_handler(exc, context)
    if response is None:
        logger.exception("unhandled error", extra={"request_id": rid})
        return Response(
            {"code": "server_error", "detail": "Something went wrong", "request_id": rid},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    detail = response.data
    if isinstance(detail, dict) and "detail" in detail and len(detail) == 1:
        detail = detail["detail"]
    elif response.status_code >= 500:
        detail = SAFE_MESSAGES.get(500, "Something went wrong")

    response.data = {
        "code": getattr(exc, "default_code", "error"),
        "detail": detail,
        "request_id": rid,
    }
    return response
