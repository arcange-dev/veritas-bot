from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from core.views import HealthView
from execution.views import DeviceViewSet, RunnerClaimView
from integrations.urls import org_urlpatterns as integration_org_urls, public_urlpatterns as integration_public_urls
from audit.views import AuditLogViewSet, NotificationViewSet
from orchestration.views import ApprovalViewSet, RunViewSet
from projects.dashboard import DashboardSummaryView
from projects.views import ProjectViewSet
from providers.views import CredentialViewSet

router = DefaultRouter()
router.register(r"credentials", CredentialViewSet, basename="credential")
router.register(r"projects", ProjectViewSet, basename="project")
router.register(r"runs", RunViewSet, basename="run")
router.register(r"approvals", ApprovalViewSet, basename="approval")
router.register(r"runners", DeviceViewSet, basename="runner")
router.register(r"notifications", NotificationViewSet, basename="notification")
router.register(r"audit", AuditLogViewSet, basename="audit")

urlpatterns = [
    path("healthz", HealthView.as_view(), name="health"),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
    # The only unauthenticated write in the API: possession of a pairing code is
    # the credential. Throttled and attempt-limited.
    path("api/v1/runners/claim/", RunnerClaimView.as_view(), name="runner-claim"),
    # Tenancy is resolved from the URL's org_id, which the permission classes read.
    path("api/v1/", include(integration_public_urls)),
    path("api/v1/orgs/<uuid:org_id>/dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("api/v1/orgs/<uuid:org_id>/", include(integration_org_urls)),
    path("api/v1/orgs/<uuid:org_id>/", include(router.urls)),
]
