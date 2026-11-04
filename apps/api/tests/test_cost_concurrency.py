"""Concurrent cost accounting must not lose updates.

The spend cap is computed from AgentRun.cost_usd. If two parallel tasks both
read the old value, add their own cost and write back, one increment vanishes
and the cap can be exceeded. This runs real threads against the real gateway.
"""
from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest

from ai.gateway import complete
from billing.models import UsageRecord
from orchestration import services
from orchestration.models import AgentRun
from projects.models import Project
from providers.crypto import encrypt_secret
from providers.models import CredentialStatus, ProviderCredential, ProviderModel

pytestmark = pytest.mark.django_db(transaction=True)

THREADS = 6
CALLS_EACH = 4
# 1000 in + 1000 out at $1/$2 per million = $0.003 per call.
PER_CALL = Decimal("0.003000")


def transport(*, settings, messages, max_tokens, temperature):
    return {"text": "ok", "input_tokens": 1000, "output_tokens": 1000, "tool_calls": []}


@pytest.fixture
def run(org, profile):
    project = Project.objects.create(organization=org, name="p", slug="p", created_by=profile)
    token, kid = encrypt_secret("sk-live-test-0000000000")
    ProviderCredential.objects.create(organization=org, provider="openai", secret_encrypted=token,
                                      key_id=kid, last4="0000", created_by=profile,
                                      status=CredentialStatus.VALID)
    ProviderModel.objects.create(provider="openai", model_id="gpt-x",
                                 input_cost_per_1m=Decimal("1"), output_cost_per_1m=Decimal("2"))
    return services.create_run(project=project, profile=profile, objective="Build a todo app",
                               cost_cap_usd=Decimal("50"))


def test_parallel_calls_never_lose_a_cost_increment(run):
    errors: list[BaseException] = []
    barrier = threading.Barrier(THREADS)

    def worker():
        from django.db import connections
        try:
            barrier.wait(timeout=10)
            for _ in range(CALLS_EACH):
                fresh = AgentRun.objects.select_related("organization").get(pk=run.pk)
                complete(run=fresh, agent_kind="backend", provider="openai", model_id="gpt-x",
                         messages=[{"role": "user", "content": "hi"}], max_tokens=1000,
                         transport=transport)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors[:2]
    total_calls = THREADS * CALLS_EACH
    recorded = UsageRecord.objects.filter(run=run)
    assert recorded.count() == total_calls

    billed = sum(u.cost_usd for u in recorded)
    stored = AgentRun.objects.get(pk=run.pk).cost_usd
    assert billed == PER_CALL * total_calls
    assert stored == billed, f"run total {stored} != sum of usage rows {billed}: updates were lost"
