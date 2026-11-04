---
name: byok-ai-provider-integration
description: Bring-your-own-key provider engineering - envelope encryption with rotation, credential lifecycle, validation probes, the model capability registry, LiteLLM routing with fallbacks that never silently bill the user, and per-task spend caps. Use when adding a provider, a model, a validation flow, or any code path that touches a user API key.
---

# BYOK AI Provider Integration

## When to use
Adding a provider or model, changing credential storage, building the settings UI contract,
or debugging "my key works in their app but not here".

## Credential model
`ProviderCredential(organization, provider, label, secret_encrypted, key_id, last4,
status, last_validated_at, created_by)`.

- `secret_encrypted` holds a Fernet token of the JSON `{"api_key": ..., "base_url": ...}`.
- `key_id` names which master key produced the token, enabling rotation.
- `last4` is the only fragment ever serialized to the client.
- Rotation: prepend a new key to `BYOK_ENCRYPTION_KEYS`, deploy, run the re-encrypt task,
  then remove the old key. Decryption always tries the `kid` recorded in the row first.

```python
# providers/crypto.py — the ONLY module allowed to decrypt
from cryptography.fernet import Fernet, MultiFernet, InvalidToken
from django.conf import settings

def _fernet() -> MultiFernet:
    return MultiFernet([Fernet(k) for k in settings.BYOK_ENCRYPTION_KEYS])

def encrypt(api_key: str, base_url: str | None = None) -> str:
    payload = json.dumps({"api_key": api_key, "base_url": base_url}).encode()
    return _fernet().encrypt(payload).decode()

def decrypt(token: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:                 # never log the token
        raise CredentialDecryptionError("credential cannot be decrypted") from exc
```

Hard rules: never return the decrypted dict from a view; never include it in a
`__repr__`, a serializer, a Celery result, or an exception message; wipe it from locals
after use where practical; never pass it into a sandbox or to `apps/web`.

## Validation probe
Cheapest authenticated call per provider, 8s timeout, one retry on 5xx only:

| Provider | Probe |
|---|---|
| openai, openrouter, deepseek, mistral, groq, together, fireworks, xai, generic | `GET /v1/models` |
| anthropic | `GET /v1/models` (falls back to a 1-token message) |
| google | `GET /v1beta/models` |
| azure_openai | `GET {endpoint}/openai/deployments?api-version=...` |
| bedrock | `bedrock:ListFoundationModels` via SigV4 |
| ollama, lmstudio | `GET /api/tags` / `GET /v1/models` on the user's base_url |

Persist `status` (`unverified|valid|invalid|revoked`), `last_validated_at`, and a
`last_error_code` — never the provider's raw error body if it could echo the key.

## Capability registry
Never assume a model's features. `ProviderModel` rows carry:
`context_window, max_output_tokens, supports_tools, supports_vision, supports_streaming,
supports_json_schema, supports_reasoning, input_cost_per_1m, output_cost_per_1m, source`.
The registry is refreshed by a nightly task per provider and is the only thing the UI and
the orchestrator read. If a capability is unknown, treat it as `False` and degrade
gracefully rather than optimistically.

## Routing

```python
# providers/router.py
def resolve_model(agent: AgentProfile, org: Organization) -> ResolvedModel:
    chain = [agent.model_ref, agent.fallback_model_ref, org_default(org)]
    for ref in filter(None, chain):
        cred = usable_credential(ref, org)
        if cred and capability_ok(ref, agent.required_capabilities):
            return ResolvedModel(cred, ref)
    raise NoUsableModel(...)
```
- Silent provider switching is forbidden when the fallback has a different price. If a
  fallback would be used, attach `fallback_reason` to the run and surface it in the UI.
- `UsageRecord` is written per model call: run, agent, model, input/output tokens,
  computed cost, `estimated=True` when pricing came from the catalogue rather than the
  provider's own usage block.
- Hard stop: before dispatch, if `run.accumulated_cost + estimated_next > task_cap` or the
  monthly cap is exceeded, fail the step with `SpendCapExceeded` and notify. Never truncate
  silently and never continue on someone else's key.

## Adapter shape
Prefer LiteLLM for breadth, with a thin native adapter where a provider's tool-calling or
streaming semantics differ (Bedrock, Azure, Anthropic extended thinking). Every adapter
returns the same `ModelResponse` Pydantic model so the graph never branches on provider.

## Checklist
- [ ] New provider has: probe, capability map, pricing row, and a test with a fake key.
- [ ] Decryption happens in exactly one module.
- [ ] No credential material in logs, traces, exceptions, or Celery results.
- [ ] Spend caps checked before dispatch and recorded after.
- [ ] Revoked/rotated key path tested.
