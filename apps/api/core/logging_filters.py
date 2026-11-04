from __future__ import annotations

import logging

from core.middleware import redact


class SecretRedactionFilter(logging.Filter):
    """Applies to every log record, including Celery and ASGI access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        record.request_id = getattr(record, "request_id", "-")
        return True
