from __future__ import annotations

from rest_framework.throttling import SimpleRateThrottle


class OrgScopedThrottle(SimpleRateThrottle):
    """Rate limit per organization, falling back to the user id."""

    scope = "org"

    def get_cache_key(self, request, view):
        org = getattr(request, "org", None)
        ident = f"org:{org.id}" if org else f"user:{getattr(request.user, 'pk', 'anon')}"
        return self.cache_format % {"scope": self.scope, "ident": ident}


class CredentialProbeThrottle(SimpleRateThrottle):
    """Stops a stolen key being used as a validation oracle."""

    scope = "probe"
    rate = "10/min"

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": getattr(request.user, "pk", "anon"),
        }
