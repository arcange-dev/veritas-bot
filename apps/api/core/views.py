from __future__ import annotations

import logging

from django.db import connection
from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Real dependency status. A health check that only says 'ok' is decoration."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        checks: dict[str, str] = {}
        healthy = True
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error:{type(exc).__name__}"
            healthy = False

        try:
            from django.core.cache import cache
            from django.conf import settings

            if settings.REDIS_URL:
                import redis

                redis.Redis.from_url(settings.REDIS_URL, socket_timeout=2).ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error:{type(exc).__name__}"
            # Redis is required for queueing, so degrade the health signal.

        return JsonResponse(
            {"status": "ok" if healthy else "degraded", "checks": checks},
            status=200 if healthy else 503,
        )
