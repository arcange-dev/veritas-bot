"""Model resolution. Silent provider switching is a billing incident, so any
fallback is recorded and surfaced."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.errors import NoUsableModel
from providers.crypto import decrypt_secret
from providers.models import CredentialStatus, ProviderCredential, ProviderModel


@dataclass(frozen=True)
class ResolvedModel:
    credential: ProviderCredential
    model: ProviderModel | None
    provider: str
    model_id: str
    fallback_reason: str = ""

    def settings(self) -> dict:
        """Decrypt at the last possible moment, for one call, and never store.

        Callers must pass this straight into the adapter and drop it.
        """
        secret = decrypt_secret(self.credential.secret_encrypted, self.credential.key_id)
        return {
            "provider": self.provider,
            "model": self.model_id,
            "api_key": secret["api_key"],
            "base_url": secret["base_url"] or self.credential.base_url,
        }


def _usable(cred: ProviderCredential | None) -> bool:
    return cred is not None and cred.status in {CredentialStatus.VALID, CredentialStatus.UNVERIFIED}


def _lookup(org, provider: str, model_id: str) -> ProviderModel | None:
    return ProviderModel.objects.filter(provider=provider, model_id=model_id).first()


def resolve_model(*, organization, provider: str, model_id: str,
                  fallback_provider: str = "", fallback_model_id: str = "",
                  required: set[str] | None = None) -> ResolvedModel:
    required = required or set()
    primary_cred = ProviderCredential.objects.filter(
        organization=organization, provider=provider
    ).first()
    primary_model = _lookup(organization, provider, model_id)

    def ok(model: ProviderModel | None) -> bool:
        return model is None or model.capability_ok(required)

    if _usable(primary_cred) and ok(primary_model):
        return ResolvedModel(primary_cred, primary_model, provider, model_id)

    if fallback_provider and fallback_model_id:
        fb_cred = ProviderCredential.objects.filter(
            organization=organization, provider=fallback_provider
        ).first()
        fb_model = _lookup(organization, fallback_provider, fallback_model_id)
        if _usable(fb_cred) and ok(fb_model):
            reason = "primary_credential_unusable" if not _usable(primary_cred) \
                else "missing_required_capability"
            return ResolvedModel(
                fb_cred, fb_model, fallback_provider, fallback_model_id,
                fallback_reason=reason,
            )

    raise NoUsableModel(
        f"No usable credential for {provider}/{model_id}. Add a key in provider settings."
    )


def monthly_spend(org) -> Decimal:
    from django.db.models import Sum

    from billing.models import UsageRecord

    total = UsageRecord.objects.filter(organization=org).aggregate(total=Sum("cost_usd"))["total"]
    return total or Decimal("0")
