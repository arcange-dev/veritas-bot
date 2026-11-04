"""Routes for the integrations app.

The org-scoped router is included by config/urls.py under /api/v1/orgs/<org_id>/;
the webhook path is public and mounted separately.
"""
from django.urls import path
from rest_framework.routers import DefaultRouter

from integrations.views import (
    DeploymentViewSet,
    GitHubIntegrationView,
    GitHubInstallStartView,
    GitHubWebhookView,
    RepositoryBranchesView,
    WebhookDeliveryViewSet,
)

router = DefaultRouter()
router.register(r"deployments", DeploymentViewSet, basename="deployment")
router.register(r"integrations/github/deliveries", WebhookDeliveryViewSet, basename="github-delivery")

org_urlpatterns = [
    path("integrations/github/", GitHubIntegrationView.as_view(), name="github-integration"),
    path("integrations/github/install/", GitHubInstallStartView.as_view(), name="github-install"),
    path("repositories/<uuid:pk>/branches/", RepositoryBranchesView.as_view(), name="repository-branches"),
    *router.urls,
]

public_urlpatterns = [
    path("webhooks/github/", GitHubWebhookView.as_view(), name="github-webhook"),
]
