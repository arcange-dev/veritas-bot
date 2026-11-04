---
name: testing-and-quality-assurance
description: Test strategy and implementation across frontend, backend, runner and cloud execution - what to test at which layer, pytest and Playwright patterns, isolation tests, fake provider and fake sandbox harnesses, and the rule against weakening tests to make a build pass. Use when writing or fixing tests, or when a build is red.
---

# Testing and QA

## When to use
Writing tests, triaging a red build, or deciding what coverage a feature needs before merge.

## Layer map
| Layer | Tool | Must cover |
|---|---|---|
| Pure logic (cost math, routing, path resolution) | pytest unit | every branch, no DB |
| API | pytest-django + DRF `APIClient` | happy path, validation errors, cross-tenant 404, auth denied |
| DB | pytest-django with a real Postgres | constraints, RLS visibility, migration reversibility |
| Orchestration | pytest with a scripted fake model | graph transitions, retries, approval resume, budget stop |
| Providers | pytest with a fake transport | encrypt/decrypt, rotation, validation probe, spend cap |
| Frontend units | Vitest + Testing Library | component states, store logic, schema parsing |
| E2E | Playwright | register -> login -> create project -> add provider -> run -> see stream |
| Runner | pytest | path escape, token scope, command deny-list, reconnect |
| Cloud | pytest, gated by env | lifecycle, non-root, TTL, egress block, cleanup |

## Backend patterns
```python
@pytest.mark.django_db
def test_cross_tenant_project_is_404(client, org_a_user, org_b_project):
    client.force_authenticate(org_a_user)
    resp = client.get(f"/api/v1/orgs/{org_a_user.org.id}/projects/{org_b_project.id}/")
    assert resp.status_code == 404          # not 403: no id enumeration

@pytest.mark.django_db
def test_credential_is_never_returned(client, org_a_user, credential):
    client.force_authenticate(org_a_user)
    body = client.get(f"/api/v1/orgs/{org_a_user.org.id}/credentials/").json()
    assert "api_key" not in json.dumps(body)
    assert body["results"][0]["last4"] == credential.last4

@pytest.mark.django_db
def test_decimal_cost_math():
    assert estimate_cost(1_000_000, 0, price_in=Decimal("3")) == Decimal("3.000000")
```
Every endpoint needs a cross-tenant test. That test is the one that catches the bug that
would end the product.

## Fake model harness
```python
class ScriptedModel:
    def __init__(self, script: list[ModelResponse]): self.script = deque(script)
    def complete(self, **_) -> ModelResponse:
        if not self.script: raise AssertionError("graph asked for an unscripted turn")
        return self.script.popleft()
```
Assert on state diffs and tool calls, not on prose. One opt-in live test per provider,
`@pytest.mark.live`, skipped unless `SUPERAGENT_LIVE=1` and a key is present.

## Playwright rules
- One happy-path spec per critical workflow; no exhaustive matrix.
- Use a seeded test account and a fake provider so E2E never spends real money.
- `--reporter=list`, trace on first retry, video off.
- Never `waitForTimeout`; wait on a state, a response, or a locator.

## Red build protocol
1. Reproduce locally with the exact command from CI.
2. Read the actual error before changing anything.
3. Fix the cause. If the test itself encodes a wrong expectation, fix the test and say why in
   the commit message.
4. Never `@skip`, `xfail`, `--no-verify`, or delete an assertion to go green. If a test is
   genuinely obsolete, delete it in its own commit with a justification.
5. Re-run the whole suite, not only the failing file.

## Checklist
- [ ] New endpoint: auth, validation, cross-tenant, success tests.
- [ ] New model: constraint test.
- [ ] New agent node: happy + failure graph test.
- [ ] Coverage of new code >= 80% by branch, measured, not assumed.
- [ ] Test output pasted into the PR or milestone report.
