"""Cross-tenant access is the defect that ends a multi-tenant product."""
import pytest
from rest_framework.exceptions import NotFound

from core.tenancy import for_org, scoped_or_404
from projects.models import Project


@pytest.fixture
def project_a(org, profile):
    return Project.objects.create(
        organization=org, name="Alpha", slug="alpha", created_by=profile
    )


@pytest.fixture
def project_b(other_org):
    return Project.objects.create(
        organization=other_org, name="Beta", slug="beta",
        created_by=other_org.created_by,
    )


def test_for_org_refuses_to_return_unscoped_rows():
    with pytest.raises(ValueError):
        for_org(Project.objects.all(), None)


def test_for_org_filters(org, project_a, project_b):
    assert list(for_org(Project.objects.all(), org)) == [project_a]


def test_scoped_or_404_hides_a_foreign_row(org, project_b):
    with pytest.raises(NotFound):
        scoped_or_404(Project.objects.all(), org, pk=project_b.pk)


def test_api_returns_404_for_another_tenants_project(api, org, project_b):
    resp = api.get(f"/api/v1/orgs/{org.id}/projects/{project_b.id}/")
    assert resp.status_code == 404


def test_api_lists_only_own_projects(api, org, project_a, project_b):
    resp = api.get(f"/api/v1/orgs/{org.id}/projects/")
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in body.get("results", body if isinstance(body, list) else [])]
    assert str(project_a.id) in ids
    assert str(project_b.id) not in ids


def test_non_member_of_org_gets_404(api, other_org):
    resp = api.get(f"/api/v1/orgs/{other_org.id}/projects/")
    assert resp.status_code == 404
