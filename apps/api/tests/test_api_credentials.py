"""BYOK end to end at the API boundary."""
import pytest

from providers.models import ProviderCredential


@pytest.mark.django_db
def test_create_credential_encrypts_and_never_returns_the_key(api, org):
    resp = api.post(
        f"/api/v1/orgs/{org.id}/credentials/",
        {"provider": "openai", "label": "work", "api_key": "sk-live-abcdef1234567890"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert "api_key" not in body
    assert body["last4"] == "7890"
    assert body["status"] == "unverified"

    stored = ProviderCredential.objects.get(id=body["id"])
    assert b"sk-live-abcdef1234567890" not in bytes(stored.secret_encrypted)

    from providers.crypto import decrypt_secret

    assert decrypt_secret(stored.secret_encrypted, stored.key_id)["api_key"] == \
        "sk-live-abcdef1234567890"


@pytest.mark.django_db
def test_base_url_required_for_local_providers(api, org):
    resp = api.post(
        f"/api/v1/orgs/{org.id}/credentials/",
        {"provider": "ollama", "api_key": "not-needed-but-required"},
        format="json",
    )
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


@pytest.mark.django_db
def test_credential_of_another_org_is_404(api, org, other_org):
    other = ProviderCredential.objects.create(
        organization=other_org, provider="openai", secret_encrypted=b"x",
        key_id="k1", last4="0000", created_by=other_org.created_by,
    )
    resp = api.get(f"/api/v1/orgs/{org.id}/credentials/{other.id}/")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_list_never_contains_key_material(api, org, profile):
    from providers.crypto import encrypt_secret

    token, kid = encrypt_secret("sk-secret-value-4321")
    ProviderCredential.objects.create(
        organization=org, provider="anthropic", secret_encrypted=token,
        key_id=kid, last4="4321", created_by=profile,
    )
    resp = api.get(f"/api/v1/orgs/{org.id}/credentials/")
    assert resp.status_code == 200
    assert "sk-secret-value" not in resp.content.decode()
