---
name: github-integration
description: GitHub App authentication and repository workflow - installation tokens, repo import, working branches, safe file commits, pull request creation, webhook signature verification, protected branch handling, and CI status reading. Use when touching repository import, git operations, PRs, or webhooks.
---

# GitHub Integration

## When to use
Repo import, branch/commit/PR flows, webhook handlers, CI status, or anything in
`apps/api/projects/github/**`.

## Authentication
Use a **GitHub App**, never a personal token, in production.

1. App private key (PEM) loaded from a file path or secret manager, never from the DB.
2. `POST /app/installations/{id}/access_tokens` -> 60-minute installation token, cached
   per installation with a 5-minute safety margin.
3. Request the narrowest permissions: `contents:write`, `pull_requests:write`,
   `metadata:read`, `checks:read`. No `admin`, no `secrets`, no org `members`.
4. Webhook payloads verified with HMAC-SHA256 over the raw body using
   `X-Hub-Signature-256`, with a constant-time compare, before any parsing.

```python
def verify_signature(raw: bytes, header: str, secret: str) -> None:
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not header or not hmac.compare_digest(expected, header):
        raise PermissionDenied("bad webhook signature")
```

## Repository import
`POST /api/v1/orgs/{org}/repositories/import {installation_id, full_name, branch}` ->
create `Repository` row -> queue `clone_and_index` -> sandbox or runner clones shallow
(`--depth=50`) -> index file tree + languages + a bounded content summary into
`RepositoryIndex` -> the analyst reads the index, not the whole repo.

Guard: repo size and file count caps, `.gitignore` respected, binaries skipped, no attempt
to fetch LFS blobs by default.

## Branch and commit discipline
- Never commit to the default branch. Always `superagent/<run-id>/<slug>`.
- Read the file's current SHA before writing; if it changed since the run read it, abort the
  write and re-plan rather than clobbering the user's edit. This is the rule that protects
  user work.
- Commit messages: `type(scope): summary` + a body listing agent steps and run id.
- PR body: objective, plan, files changed with a one-line rationale each, test evidence
  (command + result), and known limitations. Never claim tests passed unless the output is
  attached from a real run.

## Protected branches
Merging to a protected branch requires an `ApprovalRequest` and a human action. The platform
opens the PR and stops. It does not merge, does not push to main, does not force-push, and
does not enable auto-merge.

## Webhooks
Handle: `push`, `pull_request`, `installation`, `installation_repositories`,
`check_suite`, `workflow_run`. Idempotency by `X-GitHub-Delivery` stored in a table with a
unique constraint. Acknowledge fast (200 within 5s) and process in Celery. A tampered or
replayed delivery is rejected and audited.

## Checklist
- [ ] Installation token scoped to one repo and cached correctly.
- [ ] Signature verified on the raw body before JSON parse.
- [ ] Delivery id deduplicated.
- [ ] File writes compare SHAs and never overwrite unknown changes.
- [ ] PR describes real test evidence.
- [ ] No merge, no force-push, no protected-branch write anywhere in code.
