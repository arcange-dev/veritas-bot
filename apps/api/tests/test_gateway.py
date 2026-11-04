"""The LLM gateway: cap enforcement, key handling, usage, fallback honesty.

Uses the real gateway, real resolver, real database and real crypto. Only the
network transport is replaced, because tests must not spend money.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from ai.gateway import ProviderCallFailed, complete
from billing.models import UsageRecord
from core.errors import NoUsableModel, SpendCapExceeded
from orchestration.models import AgentRun
from projects.models import Project
from providers.crypto import encrypt_secret
from providers.models import CredentialStatus, ProviderCredential, ProviderModel

pytestmark = pytest.mark.django_db

SECRET = "sk-live-SUPERSECRET-0123456789"


@pytest.fixture
def project(org, profile):
    return Project.objects.create(
        organization=org, name="Demo", slug="demo", created_by=profile
    )


@pytest.fixture
def run(org, profile, project):
    return AgentRun.objects.create(
        organization=org, project=project, objective="build", created_by=profile,
        cost_cap_usd=Decimal("1.00"),
    )


def credential(org, profile, provider="openai", status=CredentialStatus.VALID, key=SECRET):
    token, kid = encrypt_secret(key)
    return ProviderCredential.objects.create(
        organization=org, provider=provider, secret_encrypted=token, key_id=kid,
        last4=key[-4:], created_by=profile, status=status,
    )


def model(provider="openai", model_id="gpt-x", inp="1.00", out="2.00"):
    return ProviderModel.objects.create(
        provider=provider, model_id=model_id,
        input_cost_per_1m=Decimal(inp), output_cost_per_1m=Decimal(out),
    )


class Recorder:
    """Stands in for the network and remembers what it was asked."""

    def __init__(self, text="done", input_tokens=1000, output_tokens=500, error=None):
        self.calls: list[dict] = []
        self.result = {"text": text, "input_tokens": input_tokens,
                       "output_tokens": output_tokens, "tool_calls": []}
        self.error = error

    def __call__(self, *, settings, messages, max_tokens, temperature):
        self.calls.append({"settings": dict(settings), "messages": messages,
                           "max_tokens": max_tokens})
        if self.error:
            raise self.error
        return self.result


def ask(run, transport, **kw):
    return complete(run=run, agent_kind="backend", provider="openai", model_id="gpt-x",
                    messages=[{"role": "user", "content": "hello"}],
                    max_tokens=kw.pop("max_tokens", 1000), transport=transport, **kw)


def test_successful_call_records_real_usage_and_cost(org, profile, run):
    credential(org, profile)
    model(inp="1.00", out="2.00")
    transport = Recorder(input_tokens=1000, output_tokens=500)

    result = ask(run, transport)

    # (1000 * 1.00 + 500 * 2.00) / 1e6 = 0.002
    assert result.cost_usd == Decimal("0.002000")
    record = UsageRecord.objects.get(run=run)
    assert (record.input_tokens, record.output_tokens) == (1000, 500)
    assert record.cost_usd == Decimal("0.002000")
    assert record.estimated is False
    run.refresh_from_db()
    assert run.cost_usd == Decimal("0.002000")


def test_the_real_key_reaches_the_transport_exactly(org, profile, run):
    credential(org, profile)
    model()
    transport = Recorder()
    ask(run, transport)
    assert transport.calls[0]["settings"]["api_key"] == SECRET


def test_spend_cap_blocks_the_call_before_it_is_made(org, profile, run):
    """The expensive failure: money must not leave before the cap is checked."""
    credential(org, profile)
    model(inp="100.00", out="100.00")   # worst case for 1000 tokens far exceeds $1.00
    transport = Recorder()

    with pytest.raises(SpendCapExceeded):
        ask(run, transport, max_tokens=50_000)

    assert transport.calls == [], "provider was called despite exceeding the cap"
    assert UsageRecord.objects.count() == 0


def test_accumulated_spend_counts_against_the_run_cap(org, profile, run):
    credential(org, profile)
    model(inp="1.00", out="1.00")
    AgentRun.objects.filter(pk=run.pk).update(cost_usd=Decimal("0.999999"))
    run.refresh_from_db()
    transport = Recorder()
    with pytest.raises(SpendCapExceeded):
        ask(run, transport, max_tokens=4000)
    assert transport.calls == []


def test_org_monthly_cap_is_enforced(org, profile, run):
    credential(org, profile)
    model()
    UsageRecord.objects.create(
        organization=org, run=run, provider="openai", model_id="gpt-x",
        cost_usd=Decimal("99.999999"),
    )
    transport = Recorder()
    with pytest.raises(SpendCapExceeded):
        ask(run, transport, org_cap=Decimal("100.00"), max_tokens=100_000)
    assert transport.calls == []


def test_no_credential_means_no_call(org, profile, run):
    transport = Recorder()
    with pytest.raises(NoUsableModel):
        ask(run, transport)
    assert transport.calls == []


def test_revoked_credential_is_not_used(org, profile, run):
    credential(org, profile, status=CredentialStatus.INVALID)
    model()
    transport = Recorder()
    with pytest.raises(NoUsableModel):
        ask(run, transport)
    assert transport.calls == []


def test_fallback_is_recorded_not_silent(org, profile, run):
    credential(org, profile, provider="openai", status=CredentialStatus.INVALID)
    credential(org, profile, provider="anthropic", key="sk-ant-backup-9999999999")
    model("anthropic", "claude-x")
    transport = Recorder()

    result = ask(run, transport, fallback_provider="anthropic", fallback_model_id="claude-x")

    assert result.provider == "anthropic"
    assert result.fallback_reason == "primary_credential_unusable"
    assert UsageRecord.objects.get(run=run).fallback_reason == "primary_credential_unusable"


def test_provider_failure_does_not_leak_the_key_or_record_usage(org, profile, run):
    credential(org, profile)
    model()
    boom = ProviderCallFailed("openai call failed (AuthenticationError)")
    transport = Recorder(error=boom)

    with pytest.raises(ProviderCallFailed) as exc:
        ask(run, transport)

    assert SECRET not in str(exc.value)
    assert UsageRecord.objects.count() == 0
    run.refresh_from_db()
    assert run.cost_usd == 0


def test_litellm_transport_swallows_provider_error_bodies(monkeypatch):
    """Provider errors can echo the request, which contains the key."""
    import litellm

    from ai.gateway import litellm_transport

    def exploding(**kwargs):
        raise RuntimeError(f"401 for key {kwargs['api_key']}")

    monkeypatch.setattr(litellm, "completion", exploding)

    with pytest.raises(ProviderCallFailed) as exc:
        litellm_transport(
            settings={"provider": "openai", "model": "gpt-x", "api_key": SECRET, "base_url": ""},
            messages=[{"role": "user", "content": "hi"}], max_tokens=10, temperature=0,
        )
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value)
    assert exc.value.__cause__ is None
