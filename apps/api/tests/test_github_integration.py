"""GitHub webhook security and the integration / deployment read APIs."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from rest_framework.test import APIClient

from integrations import github
from integrations.models import WebhookDelivery
from projects.models import Deployment, Project, Repository

SECRET = "whsec_test_secret_value_0123456789"
URL = "/api/v1/webhooks/github/"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def secret(settings):
    settings.GITHUB_WEBHOOK_SECRET = SECRET


def post(body: dict | bytes, *, event="push", delivery=None, signature="auto", content_type="application/json"):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    headers = {"HTTP_X_GITHUB_EVENT": event, "HTTP_X_GITHUB_DELIVERY": delivery or str(uuid.uuid4())}
    if signature == "auto":
        headers["HTTP_X_HUB_SIGNATURE_256"] = sign(raw)
    elif signature is not None:
        headers["HTTP_X_HUB_SIGNATURE_256"] = signature
    return APIClient().post(URL, data=raw, content_type=content_type, **headers)


# ------------------------------- webhook security ---------------------------------
@pytest.mark.django_db
def test_a_correctly_signed_push_is_accepted_and_recorded():
    r = post({"ref": "refs/heads/main", "after": "a" * 40, "repository": {"full_name": "o/r"},
              "installation": {"id": 99}})
    assert r.status_code == 202 and r.json()["handled"] is True
    row = WebhookDelivery.objects.get()
    assert (row.event, row.installation_id, row.repository_full_name, row.signature_verified) == ("push", 99, "o/r", True)
    assert row.commit_sha == "a" * 40 and len(row.payload_digest) == 64


@pytest.mark.django_db
@pytest.mark.parametrize("signature", [None, "", "sha256=", "sha256=zz", "md5=abc", "garbage",
                                       "sha256=" + "0" * 64, "sha256=" + "é" * 64, "SHA256=" + "a" * 64])
def test_missing_or_wrong_signatures_are_rejected_and_nothing_is_stored(signature):
    r = post({"a": 1}, signature=signature)
    assert r.status_code == 401
    assert WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_a_signature_made_with_the_wrong_secret_is_rejected():
    body = json.dumps({"a": 1}).encode()
    r = post(body, signature=sign(body, "some-other-secret"))
    assert r.status_code == 401 and WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_a_tampered_body_is_rejected():
    original = json.dumps({"ref": "refs/heads/main"}).encode()
    r = post(b'{"ref": "refs/heads/evil"}', signature=sign(original))
    assert r.status_code == 401 and WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_a_replayed_delivery_id_is_refused_and_not_stored_twice():
    d = str(uuid.uuid4())
    assert post({"a": 1}, delivery=d).status_code == 202
    again = post({"a": 1}, delivery=d)
    assert again.status_code == 409
    assert WebhookDelivery.objects.filter(delivery_id=d).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("delivery", ["", "short", "has spaces in it", "x" * 80, "../../etc/passwd"])
def test_a_missing_or_malformed_delivery_id_is_a_400(delivery):
    raw = json.dumps({"a": 1}).encode()
    r = APIClient().post(URL, data=raw, content_type="application/json",
                         HTTP_X_HUB_SIGNATURE_256=sign(raw), HTTP_X_GITHUB_EVENT="push",
                         HTTP_X_GITHUB_DELIVERY=delivery)
    assert r.status_code == 400 and WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_no_configured_secret_means_nothing_is_accepted(settings):
    settings.GITHUB_WEBHOOK_SECRET = ""
    raw = json.dumps({"a": 1}).encode()
    # Even an "empty secret" signature must not pass: that would be a universal key.
    r = post(raw, signature=sign(raw, ""))
    assert r.status_code == 503 and WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("body", [b"not json", b"[1,2]", b'"str"', b"\xff\xfe"])
def test_signed_but_malformed_bodies_are_400(body):
    r = post(body, signature=sign(body))
    assert r.status_code == 400 and WebhookDelivery.objects.count() == 0


@pytest.mark.django_db
def test_an_unsupported_event_is_recorded_as_ignored_not_acted_on():
    r = post({"zen": "x"}, event="star")
    assert r.status_code == 202 and r.json()["handled"] is False
    assert WebhookDelivery.objects.get().status == "ignored"


@pytest.mark.django_db
def test_hostile_payload_fields_are_bounded_not_trusted():
    r = post({"ref": "x" * 5000, "action": "y" * 5000, "repository": "not-a-dict",
              "installation": {"id": "not-an-int"}, "pull_request": {"number": -4}})
    assert r.status_code == 202
    row = WebhookDelivery.objects.get()
    assert len(row.ref) <= 200 and len(row.action) <= 40
    assert row.installation_id is None and row.pull_request_number is None


@pytest.mark.django_db
def test_the_webhook_needs_no_login_and_get_is_not_allowed():
    assert APIClient().get(URL).status_code == 405


def test_verify_signature_unit_cases():
    body = b"hello"
    good = sign(body)
    assert github.verify_signature(payload=body, signature_header=good, secret=SECRET)
    assert not github.verify_signature(payload=body, signature_header=good, secret="")
    assert not github.verify_signature(payload=b"hellO", signature_header=good, secret=SECRET)
    assert not github.verify_signature(payload=body, signature_header=None, secret=SECRET)
    assert github.verify_signature(payload=body, signature_header=good.upper().replace("SHA256=", "sha256="), secret=SECRET)


def test_an_empty_secret_never_verifies_even_a_signature_made_with_an_empty_key():
    """HMAC with an empty key is computable by anyone, so an unset secret must not
    behave as 'accept anything'. The view also answers 503 first, but this function
    can be called from elsewhere and must be safe on its own."""
    body = b'{"anything": true}'
    forged = "sha256=" + hmac.new(b"", body, hashlib.sha256).hexdigest()
    assert github.verify_signature(payload=body, signature_header=forged, secret="") is False
    assert github.verify_signature(payload=body, signature_header=forged, secret="   ".strip()) is False


# ------------------------------ org-scoped read APIs ------------------------------
@pytest.fixture
def world(org, profile, other_org):
    project = Project.objects.create(organization=org, name="Mine", slug="mine", created_by=profile)
    repo = Repository.objects.create(project=project, installation_id=7, full_name="me/app")
    dep = Deployment.objects.create(project=project, environment="staging", status="succeeded",
                                    commit_sha="b" * 40, config={"build_log": ["install", {"step": "build", "detail": "ok"}],
                                                                    "secret_token": "ghp_SHOULD_NEVER_LEAK"})
    foreign_project = Project.objects.create(organization=other_org, name="Theirs", slug="theirs",
                                             created_by=other_org.created_by)
    foreign_repo = Repository.objects.create(project=foreign_project, installation_id=8, full_name="them/app")
    foreign_dep = Deployment.objects.create(project=foreign_project, status="failed")
    return dict(org=org, project=project, repo=repo, dep=dep, foreign_repo=foreign_repo, foreign_dep=foreign_dep)


def base(org):
    return f"/api/v1/orgs/{org.id}"


def test_integration_view_reports_unconfigured_honestly_and_lists_only_own_repos(api, world):
    r = api.get(f"{base(world['org'])}/integrations/github/")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert [x["full_name"] for x in body["repositories"]] == ["me/app"]
    assert body["repositories"][0]["project_name"] == "Mine"
    assert body["installations"] == [{"installation_id": 7, "repository_count": 1}]


def test_install_start_is_a_409_with_the_verbatim_message_when_unconfigured(api, world):
    r = api.post(f"{base(world['org'])}/integrations/github/install/")
    assert r.status_code == 409
    assert r.json()["detail"] == "GitHub App is not configured on this server"


def test_install_start_returns_a_url_only_with_id_key_and_slug(api, world, settings):
    settings.GITHUB_APP_ID, settings.GITHUB_APP_PRIVATE_KEY = "123", "-----BEGIN-----"
    assert api.post(f"{base(world['org'])}/integrations/github/install/").status_code == 409  # no slug
    settings.GITHUB_APP_SLUG = "veritas-bot"
    r = api.post(f"{base(world['org'])}/integrations/github/install/")
    assert r.status_code == 200 and r.json()["url"].startswith("https://github.com/apps/veritas-bot/installations/new")


def test_deployments_list_detail_and_secret_config_never_leaks(api, world):
    org = world["org"]
    lst = api.get(f"{base(org)}/deployments/").json()
    rows = lst["results"] if isinstance(lst, dict) else lst
    assert [d["id"] for d in rows] == [str(world["dep"].id)]
    detail = api.get(f"{base(org)}/deployments/{world['dep'].id}/")
    assert detail.status_code == 200
    body = detail.json()
    assert body["repository_full_name"] == "me/app" and body["project_name"] == "Mine"
    assert [e["step"] for e in body["build_log"]] == ["install", "build"]
    assert "ghp_SHOULD_NEVER_LEAK" not in json.dumps(body)
    assert "secret_token" not in body["config"]


def test_cross_tenant_ids_are_404(api, world):
    org = world["org"]
    assert api.get(f"{base(org)}/deployments/{world['foreign_dep'].id}/").status_code == 404
    assert api.get(f"{base(org)}/repositories/{world['foreign_repo'].id}/branches/").status_code == 404
    assert api.post(f"{base(org)}/deployments/{world['foreign_dep'].id}/request-rollback/").status_code == 404


def test_branches_report_not_synced_instead_of_inventing_data(api, world):
    r = api.get(f"{base(world['org'])}/repositories/{world['repo'].id}/branches/")
    assert r.status_code == 200
    body = r.json()
    assert body["synced"] is False and body["branches"] == [] and body["pull_requests"] == []


def test_rollback_is_never_executed_directly(api, world):
    r = api.post(f"{base(world['org'])}/deployments/{world['dep'].id}/request-rollback/")
    assert r.status_code == 409 and "approved agent run" in r.json()["detail"]
    world["dep"].refresh_from_db()
    assert world["dep"].status == "succeeded"


def test_deployments_are_read_only_over_http(api, world):
    org = world["org"]
    assert api.post(f"{base(org)}/deployments/", {"environment": "preview"}, format="json").status_code == 405
    assert api.delete(f"{base(org)}/deployments/{world['dep'].id}/").status_code == 405


def test_deliveries_only_show_this_orgs_verified_installations(api, world):
    WebhookDelivery.objects.create(delivery_id="d-mine-0001", event="push", installation_id=7, signature_verified=True)
    WebhookDelivery.objects.create(delivery_id="d-theirs-01", event="push", installation_id=8, signature_verified=True)
    WebhookDelivery.objects.create(delivery_id="d-unknown-1", event="push", installation_id=None, signature_verified=True)
    r = api.get(f"{base(world['org'])}/integrations/github/deliveries/").json()
    rows = r["results"] if isinstance(r, dict) else r
    assert [d["delivery_id"] for d in rows] == ["d-mine-0001"]


def test_anonymous_callers_are_401(world):
    assert APIClient().get(f"{base(world['org'])}/deployments/").status_code == 401
