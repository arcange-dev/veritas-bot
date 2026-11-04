from __future__ import annotations

from rest_framework import serializers

from providers.models import ProviderCredential, ProviderModel


class CredentialSerializer(serializers.ModelSerializer):
    """Write-only api_key in, last4 out. The plaintext never leaves the server."""

    api_key = serializers.CharField(write_only=True, required=True, min_length=8,
                                   max_length=4096, trim_whitespace=True)

    class Meta:
        model = ProviderCredential
        fields = ["id", "provider", "label", "base_url", "status",
                  "last4", "last_validated_at", "last_error_code", "api_key",
                  "created_at"]
        read_only_fields = ["id", "status", "last4", "last_validated_at",
                            "last_error_code", "created_at"]

    def validate(self, attrs):
        provider = attrs.get("provider")
        base_url = attrs.get("base_url", "")
        if provider in {"ollama", "lmstudio", "openai_compatible", "azure_openai"} and not base_url:
            raise serializers.ValidationError(
                {"base_url": "This provider requires a base URL."}
            )
        if base_url and not base_url.startswith(("http://", "https://")):
            raise serializers.ValidationError({"base_url": "Must be an http(s) URL."})
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data.pop("api_key", None)
        return data


class ProviderModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProviderModel
        fields = ["id", "provider", "model_id", "display_name", "context_window",
                  "max_output_tokens", "supports_tools", "supports_vision",
                  "supports_streaming", "supports_json_schema", "supports_reasoning",
                  "input_cost_per_1m", "output_cost_per_1m", "is_deprecated"]
