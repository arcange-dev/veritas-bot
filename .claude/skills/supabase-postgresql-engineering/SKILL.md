---
name: supabase-postgresql-engineering
description: Database engineering for Supabase Postgres behind Django - schema conventions, UUID keys, indexes, constraints, RLS policies that mirror Django permissions, connection pooling for Render, and safe migration sequencing. Use when designing tables, writing migrations, tuning queries, or configuring RLS.
---

# Supabase + PostgreSQL Engineering

## When to use
Any schema change, migration, index, RLS policy, or query-performance work.

## Conventions
- Primary keys are `UUIDField(default=uuid4, editable=False)`.
- Timestamps: `created_at` (auto_now_add), `updated_at` (auto_now). Soft delete only
  where product requires it, via `deleted_at` + a partial index.
- Every tenant table: `organization_id UUID NOT NULL` with `on_delete=PROTECT`.
- Money: `Numeric(12, 6)` in USD. Never float. Store token counts as `BigInteger`.
- Enums: use `TextChoices` and a `CheckConstraint`, not a Postgres enum type (enums are
  painful to alter and Django can't reverse them cleanly).
- Constraint names are explicit and stable.

```python
class Meta:
    constraints = [
        models.UniqueConstraint(fields=["organization", "name"],
                                name="uniq_project_org_name"),
        models.CheckConstraint(check=Q(role__in=["owner","admin","member","viewer"]),
                               name="ck_membership_role"),
    ]
    indexes = [
        models.Index(fields=["organization", "-created_at"], name="idx_run_org_created"),
        models.Index(fields=["status"], condition=Q(status="running"),
                     name="idx_run_running_partial"),
    ]
```

## RLS: mirror Django, do not replace it
Django connects as the database owner and bypasses RLS unless forced. RLS is a second
wall for anything that reaches Postgres directly (Supabase client, analytics, future
services). Write policies for every tenant table:

```sql
ALTER TABLE projects_project ENABLE ROW LEVEL SECURITY;

CREATE POLICY project_select_own_org ON projects_project
FOR SELECT USING (
  organization_id IN (
    SELECT organization_id FROM identity_membership
    WHERE user_id = (SELECT id FROM identity_profile
                     WHERE supabase_user_id = auth.uid())
      AND is_active
  )
);

CREATE POLICY project_write_admin ON projects_project
FOR ALL USING (
  organization_id IN (
    SELECT m.organization_id FROM identity_membership m
    JOIN identity_profile p ON p.id = m.user_id
    WHERE p.supabase_user_id = auth.uid()
      AND m.is_active AND m.role IN ('owner','admin')
  )
);
```
Keep the policy SQL in the same migration that creates the table, and add a test that
asserts a foreign org's row is invisible.

## Connection management on Render
- Web tier: Supabase **pooled** connection (pgbouncer, transaction mode), `CONN_MAX_AGE=0`
  with pgbouncer, or `CONN_MAX_AGE=60` on direct. Never exceed the pool.
- Migrations and Celery: direct connection string (`DATABASE_DIRECT_URL`).
- `ATOMIC_REQUESTS=False` by default; opt in per view where a request is one transaction.

## Query rules
- `EXPLAIN (ANALYZE, BUFFERS)` any query over 50ms in staging before shipping.
- No `SELECT *` from Python (`only()`/`values()` where the row is wide).
- Keyset pagination for run/step/usage tables; `OFFSET` only under 10k rows.
- Avoid N+1: assert with `django_assert_num_queries` in tests for list endpoints.

## Migration safety sequence
1. Add nullable column / new table.
2. Backfill in a batched Celery task (1k rows per batch, sleep between).
3. Add constraint `NOT VALID`, then `VALIDATE CONSTRAINT`.
4. Switch reads, later drop the old column in a separate release.

## Checklist
- [ ] UUID pk, org FK, explicit index names.
- [ ] Reversible migration or documented irreversible step.
- [ ] RLS enabled + policy + isolation test.
- [ ] No float money, no naive datetimes (`USE_TZ=True`).
