"""BYOK storage. The plaintext key exists only inside providers/crypto.py's callers."""
from __future__ import annotations

from django.db import models

from core.models import OrgScopedModel, TimeStampedModel, UUIDModel


class ProviderSlug(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    GOOGLE = "google", "Google Gemini"
    OPENROUTER = "openrouter", "OpenRouter"
    XAI = "xai", "xAI"
    DEEPSEEK = "deepseek", "DeepSeek"
    MISTRAL = "mistral", "Mistral"
    GROQ = "groq", "Groq"
    TOGETHER = "together", "Together AI"
    FIREWORKS = "fireworks", "Fireworks AI"
    BEDROCK = "bedrock", "AWS Bedrock"
    AZURE_OPENAI = "azure_openai", "Azure OpenAI"
    OLLAMA = "ollama", "Ollama"
    LMSTUDIO = "lmstudio", "LM Studio"
    OPENAI_COMPATIBLE = "openai_compatible", "OpenAI-compatible"


class CredentialStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Unverified"
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    REVOKED = "revoked", "Revoked"


class ProviderCredential(OrgScopedModel):
    provider = models.CharField(max_length=40, choices=ProviderSlug.choices)
    label = models.CharField(max_length=80, blank=True)
    secret_encrypted = models.BinaryField()
    key_id = models.CharField(max_length=16, default="k1")
    last4 = models.CharField(max_length=4, blank=True)
    base_url = models.URLField(blank=True)
    status = models.CharField(
        max_length=20, choices=CredentialStatus.choices, default=CredentialStatus.UNVERIFIED
    )
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=60, blank=True)
    created_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, related_name="credentials"
    )

    class Meta:
        db_table = "providers_credential"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "provider", "label"],
                name="uniq_credential_org_provider_label",
            )
        ]
        indexes = [
            models.Index(fields=["organization", "provider"], name="idx_cred_org_provider"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.last4} ({self.status})"

    def __repr__(self) -> str:
        # Explicitly exclude secret_encrypted: reprs end up in logs and Sentry.
        return f"<ProviderCredential {self.provider} ****{self.last4} {self.status}>"


class ProviderModel(UUIDModel, TimeStampedModel):
    """Capability registry.

    Not org-scoped on purpose: it is a global catalogue of provider facts. Any
    model that IS org-specific (a custom Ollama endpoint) belongs on
    ProviderCredential.base_url instead.
    """

    provider = models.CharField(max_length=40, choices=ProviderSlug.choices)
    model_id = models.CharField(max_length=160)
    display_name = models.CharField(max_length=160, blank=True)
    context_window = models.PositiveIntegerField(default=0)
    max_output_tokens = models.PositiveIntegerField(default=0)
    supports_tools = models.BooleanField(default=False)
    supports_vision = models.BooleanField(default=False)
    supports_streaming = models.BooleanField(default=True)
    supports_json_schema = models.BooleanField(default=False)
    supports_reasoning = models.BooleanField(default=False)
    input_cost_per_1m = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    output_cost_per_1m = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    is_deprecated = models.BooleanField(default=False)
    source = models.CharField(max_length=40, default="manual")
    refreshed_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "providers_model"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "model_id"], name="uniq_provider_model"
            )
        ]
        indexes = [models.Index(fields=["provider"], name="idx_model_provider")]

    def __str__(self) -> str:
        return f"{self.provider}/{self.model_id}"

    def capability_ok(self, required: set[str]) -> bool:
        """Unknown capability is treated as unsupported, never assumed."""
        return all(bool(getattr(self, f"supports_{cap}", False)) for cap in required)
