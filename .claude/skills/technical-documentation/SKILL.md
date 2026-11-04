---
name: technical-documentation
description: Writing and maintaining the project's documentation set - README, ARCHITECTURE, DECISIONS (ADRs), API reference, security and testing reports, PROJECT_STATUS honesty rules, and changelog discipline. Use when documenting a feature, recording a decision, or updating status after a session.
---

# Technical Documentation

## When to use
After any behaviour change, when recording a decision, when onboarding needs a map, or at a
milestone boundary.

## The document set
| File | Audience | Rule |
|---|---|---|
| `README.md` | new dev | runnable in under 5 commands |
| `docs/architecture/ARCHITECTURE.md` | engineers | diagrams + boundaries, updated with the code |
| `docs/architecture/DECISIONS.md` | engineers | append-only ADRs |
| `docs/api/API.md` | frontend + integrators | generated from contracts, plus auth notes |
| `docs/security/SECURITY_REPORT.md` | reviewers | findings with severity and status |
| `docs/deployment/DEPLOYMENT.md` | ops | exact commands per environment |
| `TESTING_REPORT.md` | everyone | what was actually run, with output |
| `PROJECT_STATUS.md` | everyone | honest current state |
| `CHANGELOG.md` | users | user-visible changes only |

## ADR format
```markdown
## ADR-007: Postgres checkpointer instead of Redis for LangGraph state

Date: 2026-10-30
Status: accepted

Context: runs must survive worker restarts and be resumable days later.
Decision: use langgraph-checkpoint-postgres keyed by run_id.
Alternatives: Redis (fast, lossy on eviction), custom table (extra code).
Consequences: +durability, +queryable state for the UI; -write amplification on large state,
so large artifacts go to object storage and state holds references.
```

## API docs
Generate the OpenAPI schema from DRF (`drf-spectacular`) in CI and fail the build if it
cannot be generated. Document: auth scheme, tenancy header, error envelope, pagination,
rate limits, and the streaming protocol. Every endpoint entry shows one curl example and
one typed response.

## PROJECT_STATUS honesty rules
- Three sections only: **Verified working**, **Implemented but unverified**, **Not started**.
- "Verified working" requires a command a reader could re-run and the output you saw.
- Never move something to verified because it compiles or because an agent said so.
- Bugs list includes reproduction steps, not just a title.
- Always end with the next three concrete actions.

## Changelog
`## [unreleased]` with `Added / Changed / Fixed / Security / Removed`. One line per
user-visible change. No commit-speak, no "misc improvements".

## Writing rules
- Lead with what the reader needs to do, then why.
- Prose over bullet soup for decisions; bullets for procedures.
- Every diagram has a one-line caption stating the invariant it shows.
- No em dashes. Use a period or a comma.
- Delete stale docs. A wrong doc is worse than a missing one.

## Checklist
- [ ] Behaviour change has a doc change in the same commit.
- [ ] New env var in `.env.example` and the deployment table.
- [ ] ADR added for any decision a future engineer would question.
- [ ] Status file reflects reality, including what broke.
