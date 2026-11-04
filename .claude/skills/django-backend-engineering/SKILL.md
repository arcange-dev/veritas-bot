---
name: django-backend-engineering
description: Django 5 + DRF conventions for apps/api - app layout, service layer, serializers, permission classes, Supabase JWT authentication, Celery task design, error envelope, and pagination. Use when adding models, views, endpoints, background tasks, or auth logic.
---

# Django Backend Engineering

## When to use
Any change inside `apps/api`.

## App layout
```
apps/api/
  config/settings/{base,dev,test,prod}.py
  config/urls.py  config/asgi.py  config/celery.py
  core/            # tenancy, permissions, pagination, errors, middleware
  identity/        # profile, org, membership, supabase auth
  providers/       # BYOK credentials, crypto, catalogue, validation
  projects/        # projects, repos, files
  orchestration/   # runs, steps, graphs, checkpoints
  tools/           # registry, schemas, dispatch, audit
  execution/       # base, registry, local, daytona, views
  billing/         # usage, spend caps
  audit/           # audit log writer
```

## Thin views, real services
A view validates and delegates. Business rules live in `services.py` inside the app.

```python
# providers/views.py
class CredentialListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsOrgMember]
    serializer_class = CredentialSerializer

    def get_queryset(self):
        return for_org(ProviderCredential.objects.all(), self.request.org)

    def perform_create(self, serializer):
        serializer.save(
            organization=self.request.org,
            created_by=self.request.user.profile,
            secret=encrypt_credential(serializer.validated_data.pop("api_key")),
        )
```
Note: the raw key is popped before `save`, encrypted, and never re-serialized.

## Permission classes
```python
# core/permissions.py
class IsOrgMember(BasePermission):
    def has_permission(self, request, view):
        org_id = view.kwargs.get("org_id") or request.headers.get("X-Org-Id")
        membership = Membership.objects.filter(
            user=request.user, organization_id=org_id, is_active=True
        ).select_related("organization").first()
        if not membership:
            raise NotFound()          # 404, never 403, to prevent id enumeration
        request.org = membership.organization
        request.membership = membership
        return True

class IsOrgAdmin(IsOrgMember):
    def has_permission(self, request, view):
        return super().has_permission(request, view) and request.membership.role in {
            "owner", "admin"
        }
```

## Supabase JWT authentication
- Verify with Supabase JWKS (RS256/ES256) or the project JWT secret (HS256), never by
  trusting the `sub` claim unverified.
- Cache JWKS for 5 minutes; on `kid` miss, refetch once, then fail closed.
- Map `sub` -> `Profile` lazily on first authenticated request, creating the profile row.
- Reject tokens with `aud` other than `authenticated`, or `exp` in the past.

## Celery
- One task per unit of retryable work; pass ids, not objects.
- `acks_late=True`, `max_retries=3`, exponential backoff with jitter, and an idempotency
  guard on `step_id`/`run_id`.
- Queues: `default`, `agents` (long LLM turns), `execution` (sandbox ops).
- Never retry a non-idempotent external call (a git push, a PR creation) without checking
  whether it already landed.

## Error envelope
All 4xx/5xx return `{"code": "...", "detail": "...", "request_id": "..."}` via a custom
exception handler. `detail` never contains a stack trace, a query, or a credential.

## Checklist
- [ ] Queryset goes through `for_org`.
- [ ] Serializer validates every field; no `fields = "__all__"` on tenant models.
- [ ] `select_related`/`prefetch_related` on any list endpoint.
- [ ] Permission class present and tested with a second org's data.
- [ ] Migration created and reversible.
