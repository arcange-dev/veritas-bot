"""The only code that talks to a model provider.

Contract, enforced here and nowhere else:
  1. The spend cap is checked BEFORE the call, from a token estimate.
  2. The credential is decrypted for exactly one call and never stored.
  3. Usage is recorded AFTER the call from the provider's real token counts.
  4. A fallback is surfaced in the usage row, never taken silently.
  5. Provider error bodies are never returned: they can echo request data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import F
from typing import Any, Protocol

from billing.costs import check_caps, estimate_cost, estimate_tokens
from core.rls import bound
from billing.models import UsageRecord
from core.errors import NoUsableModel
from providers.router import ResolvedModel, monthly_spend, resolve_model

logger = logging.getLogger(__name__)

DEFAULT_ORG_CAP = Decimal("100.00")


class ProviderCallFailed(RuntimeError):
    """A provider call failed. The message is safe to show; it never includes the key."""


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    provider: str
    model_id: str
    fallback_reason: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class Transport(Protocol):
    """Swappable so tests exercise the real gateway with no network."""

    def __call__(self, *, settings: dict[str, Any], messages: list[dict[str, Any]],
                 max_tokens: int, temperature: float) -> dict[str, Any]: ...


def litellm_transport(*, settings: dict[str, Any], messages: list[dict[str, Any]],
                      max_tokens: int, temperature: float) -> dict[str, Any]:
    import litellm

    # LiteLLM wants "provider/model" for most vendors; OpenAI-compatible endpoints
    # go through the openai route with an explicit base_url.
    provider = settings["provider"]
    model = settings["model"]
    routed = model if "/" in model and provider in {"openrouter", "together", "fireworks"} \
        else f"{provider}/{model}"

    try:
        response = litellm.completion(
            model=routed,
            messages=messages,
            api_key=settings["api_key"],
            api_base=settings.get("base_url") or None,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=60,
            num_retries=0,    # retries belong to the orchestrator, where they are counted
        )
    except Exception as exc:  # noqa: BLE001
        # Deliberately do not include str(exc): provider errors can echo the request.
        raise ProviderCallFailed(f"{provider} call failed ({type(exc).__name__})") from None

    usage = getattr(response, "usage", None)
    choice = response.choices[0].message
    return {
        "text": getattr(choice, "content", "") or "",
        "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "tool_calls": [
            {"name": c.function.name, "arguments": c.function.arguments}
            for c in (getattr(choice, "tool_calls", None) or [])
        ],
    }


def complete(
    *,
    run,
    agent_kind: str,
    provider: str,
    model_id: str,
    messages: list[dict[str, Any]],
    fallback_provider: str = "",
    fallback_model_id: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    org_cap: Decimal = DEFAULT_ORG_CAP,
    transport: Transport = litellm_transport,
) -> Completion:

    # --- 1. resolve + pre-flight, in one SHORT transaction -----------------------
    # Nothing is held open across the network call below: a transaction that
    # waits on a remote model keeps row locks, and parallel tasks then deadlock
    # on the run row.
    with bound():
        # An explicit, bound load. `run.organization` would be a hidden query that
        # RLS filters out when it happens to run outside a bound transaction.
        from identity.models import Organization

        organization = Organization.objects.get(pk=run.organization_id)
        resolved: ResolvedModel = resolve_model(
            organization=organization, provider=provider, model_id=model_id,
            fallback_provider=fallback_provider, fallback_model_id=fallback_model_id,
        )

        in_rate = out_rate = Decimal("0")
        if resolved.model is not None:
            in_rate = Decimal(str(resolved.model.input_cost_per_1m or 0))
            out_rate = Decimal(str(resolved.model.output_cost_per_1m or 0))

        prompt_estimate = sum(estimate_tokens(str(m.get("content", ""))) for m in messages)
        worst_case = estimate_cost(prompt_estimate, max_tokens, in_rate, out_rate)
        check_caps(
            spent=Decimal(run.cost_usd), next_estimate=worst_case,
            run_cap=Decimal(run.cost_cap_usd), org_cap=org_cap,
            monthly_spent=monthly_spend(organization),
        )
        # Decrypt inside the same short window; the secret never outlives this call.
        settings = resolved.settings()

    # --- 2. one call, key decrypted and dropped (no transaction open) -----------
    try:
        raw = transport(settings=settings, messages=messages,
                        max_tokens=max_tokens, temperature=temperature)
    finally:
        settings["api_key"] = ""
        del settings

    # --- 3. record real usage ---------------------------------------------------
    cost = estimate_cost(raw["input_tokens"], raw["output_tokens"], in_rate, out_rate)
    with bound():
        UsageRecord.objects.create(
            organization=organization, run=run, agent_kind=agent_kind,
            provider=resolved.provider, model_id=resolved.model_id,
            credential=resolved.credential,
            input_tokens=raw["input_tokens"], output_tokens=raw["output_tokens"],
            cost_usd=cost, estimated=resolved.model is None,
            fallback_reason=resolved.fallback_reason,
        )
        # Atomic increment in SQL. The previous read-add-write lost updates when
        # two parallel tasks finished together, and it is what deadlocked.
        type(run).objects.filter(pk=run.pk).update(cost_usd=F("cost_usd") + cost)
        run.refresh_from_db(fields=["cost_usd"])

    return Completion(
        text=raw["text"], input_tokens=raw["input_tokens"],
        output_tokens=raw["output_tokens"], cost_usd=cost,
        provider=resolved.provider, model_id=resolved.model_id,
        fallback_reason=resolved.fallback_reason,
        tool_calls=list(raw.get("tool_calls", [])),
    )
