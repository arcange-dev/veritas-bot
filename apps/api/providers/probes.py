"""Cheapest authenticated call per provider, used to validate a user's key.

A probe must never leak the key: no URL parameters, and error bodies are mapped
to a short code rather than echoed back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

PROBE_TIMEOUT = 8.0


@dataclass
class ProbeResult:
    ok: bool
    error_code: str = ""
    detail: str = ""
    model_count: int = 0


SIMPLE_MODELS_PROBE = {
    "openai": ("https://api.openai.com/v1/models", "Authorization"),
    "openrouter": ("https://openrouter.ai/api/v1/models", "Authorization"),
    "deepseek": ("https://api.deepseek.com/v1/models", "Authorization"),
    "mistral": ("https://api.mistral.ai/v1/models", "Authorization"),
    "groq": ("https://api.groq.com/openai/v1/models", "Authorization"),
    "together": ("https://api.together.xyz/v1/models", "Authorization"),
    "fireworks": ("https://api.fireworks.ai/inference/v1/models", "Authorization"),
    "xai": ("https://api.x.ai/v1/models", "Authorization"),
    "anthropic": ("https://api.anthropic.com/v1/models", "x-api-key"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/models", "x-goog-api-key"),
}


def probe(provider: str, api_key: str, base_url: str = "") -> ProbeResult:
    """Never raises. Returns a structured result the API can persist."""
    try:
        if provider in {"ollama", "lmstudio", "openai_compatible"}:
            root = (base_url or "").rstrip("/")
            if not root:
                return ProbeResult(False, "base_url_required", "Set a base URL first")
            url = f"{root}/v1/models" if provider != "ollama" else f"{root}/api/tags"
            with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False) as client:
                resp = client.get(url)
            return _classify(resp)

        if provider in SIMPLE_MODELS_PROBE:
            url, header = SIMPLE_MODELS_PROBE[provider]
            headers = {"Authorization": f"Bearer {api_key}"}
            if header == "x-api-key":
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
            elif header == "x-goog-api-key":
                headers = {"x-goog-api-key": api_key}
            with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False) as client:
                resp = client.get(url, headers=headers)
            return _classify(resp)

        if provider == "azure_openai":
            root = (base_url or "").rstrip("/")
            if not root:
                return ProbeResult(False, "base_url_required", "Set your Azure endpoint")
            with httpx.Client(timeout=PROBE_TIMEOUT, follow_redirects=False) as client:
                resp = client.get(
                    f"{root}/openai/models?api-version=2024-06-01",
                    headers={"api-key": api_key},
                )
            return _classify(resp)

        if provider == "bedrock":
            # Full SigV4 signing lives in the adapter; here we only check the
            # shape of the credential pair the user entered.
            if not api_key or ":" not in api_key:
                return ProbeResult(False, "invalid_credential", "Expected ACCESS_KEY:SECRET")
            return ProbeResult(True, detail="Credential shape accepted; verify with a call")

        return ProbeResult(False, "unsupported_provider", provider)
    except httpx.TimeoutException:
        return ProbeResult(False, "timeout", "Provider did not respond in time")
    except httpx.HTTPError as exc:
        logger.info("probe transport error provider=%s type=%s", provider, type(exc).__name__)
        return ProbeResult(False, "network_error", "Could not reach the provider")
    except Exception as exc:  # never surface a raw provider payload
        logger.warning("probe failed provider=%s type=%s", provider, type(exc).__name__)
        return ProbeResult(False, "probe_error", "Validation failed")


def _classify(resp: httpx.Response) -> ProbeResult:
    if resp.status_code == 200:
        try:
            body = resp.json()
        except Exception:
            return ProbeResult(True, model_count=0)
        items = body.get("data") or body.get("models") or []
        return ProbeResult(True, model_count=len(items) if isinstance(items, list) else 0)
    if resp.status_code in (401, 403):
        return ProbeResult(False, "invalid_credential", "The provider rejected this key")
    if resp.status_code == 429:
        return ProbeResult(False, "rate_limited", "Provider rate limited the check")
    if resp.status_code >= 500:
        return ProbeResult(False, "provider_error", "Provider is having trouble")
    return ProbeResult(False, f"http_{resp.status_code}", "Unexpected response")
