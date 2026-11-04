# Rule: schema and migrations

- Django migrations are authoritative. Never mutate `django_migrations` and never
  apply schema DDL by hand against Supabase.
- Every migration must be reversible or explicitly documented as irreversible.
- Add indexes for any column used in a `WHERE`, `ORDER BY`, or join in a hot path.
- Destructive migrations (removing a column or table, rewriting data) require a plan
  in the PR description and a backup note.
- Constraint names are explicit: `uniq_<table>_<cols>`, `idx_<table>_<col>`.
- RLS policies mirror the Django permission model. When you add a tenant-scoped
  table, add its policy in the same migration.
