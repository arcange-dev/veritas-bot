"""Guardrail: every org-scoped route must run inside a tenant-bound transaction.

A view that forgets TenantBoundMixin would silently skip row-level security
and rely on the ORM filter alone. This walks the real URL table, so adding a
new org-scoped endpoint without the mixin fails CI instead of shipping a hole.
"""
from __future__ import annotations

from django.urls import URLPattern, URLResolver, get_resolver

from core.rls import TenantBoundMixin

# Org-scoped routes that are deliberately NOT tenant-bound, each with the reason.
EXEMPT = {
    # Authenticated by a single-use pairing code, before any org/profile exists.
    "RunnerClaimView": "device pairing happens before a tenant is known",
    # DRF's generated index of endpoint URLs. It performs no queries, so there
    # is no row for a policy to protect.
    "APIRootView": "static endpoint index; touches no database rows",
}


def _walk(patterns, prefix=""):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            yield prefix + str(p.pattern), p


def _view_class(pattern):
    cb = pattern.callback
    return getattr(cb, "cls", None) or getattr(cb, "view_class", None)


def test_every_org_scoped_view_is_tenant_bound():
    unbound, seen = [], 0
    for route, pattern in _walk(get_resolver().url_patterns):
        if "<uuid:org_id>" not in route:
            continue
        cls = _view_class(pattern)
        if cls is None:
            continue
        seen += 1
        if cls.__name__ in EXEMPT:
            continue
        if not issubclass(cls, TenantBoundMixin):
            unbound.append(f"{cls.__name__} ({route})")
    assert seen >= 5, "the walker found too few routes; the test is not looking at the real table"
    assert not unbound, "org-scoped views missing TenantBoundMixin:\n  " + "\n  ".join(sorted(set(unbound)))


def test_exemptions_still_exist_and_are_justified():
    names = {_view_class(p).__name__ for _, p in _walk(get_resolver().url_patterns) if _view_class(p)}
    stale = set(EXEMPT) - names
    assert not stale, f"stale exemptions (view no longer exists): {stale}"
    assert all(reason.strip() for reason in EXEMPT.values())
