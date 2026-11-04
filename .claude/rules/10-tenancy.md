# Rule: multi-tenancy

- Every tenant-scoped model has `organization = FK(Organization)`.
- Querysets are filtered through `apps/api/core/tenancy.py::for_org()`. Do not
  hand-roll `filter(organization_id=...)` in views.
- Permission classes derive the org from the authenticated membership, never from
  the URL or body.
- Cross-tenant access returns 404, not 403, so IDs are not enumerable.
- Any new model without an `organization` field needs an explicit comment saying
  why it is global (e.g. `ProviderModel` catalogue rows).
