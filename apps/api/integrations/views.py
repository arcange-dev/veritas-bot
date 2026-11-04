"""GitHub integration, webhook receiver and deployment read APIs.

Tenancy
-------
The org-scoped views follow the project rules: ``TenantBoundMixin`` first, a
role permission, and only ``*_id`` columns across relations. ``Repository`` and
``Deployment`` have no organization column; they belong to a project, and both
the ORM filter (``project__organization_id``) and the RLS EXISTS policy enforce
that. The webhook is the one unauthenticated route, so it has no tenant at all.
"""
from __future__ import annotations

import json
import logging

from django.db import IntegrityError, transaction
from django.views.decorators.csrf import csrf_exempt
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import DomainError
from core.permissions import IsOrgMember
from core.rls import TenantBoundMixin
from integrations import github
from integrations.models import WebhookDelivery, WebhookDeliveryStatus
from integrations.serializers import (
    DeploymentDetailSerializer,
    DeploymentSerializer,
    RepositorySerializer,
    WebhookDeliverySerializer,
)
from projects.models import Deployment, Project, Repository

logger = logging.getLogger(__name__)

# GitHub caps webhook bodies at 25 MB. Anything bigger is refused before it is
# read into memory, so an unauthenticated caller cannot make us buffer it.
MAX_WEBHOOK_BYTES = 26 * 1024 * 1024


class GitHubNotConfigured(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "github_not_configured"

    def __init__(self, detail: str = "GitHub App is not configured on this server"):
        super().__init__(detail)


class DeploymentNotDirect(DomainError):
    status_code = status.HTTP_409_CONFLICT
    code = "deployment_not_direct"


def _project_labels(organization_id) -> dict:
    """One query for every project name/slug in the org, instead of one per row."""
    return {
        row["id"]: {"name": row["name"], "slug": row["slug"]}
        for row in Project.objects.filter(organization_id=organization_id).values("id", "name", "slug")
    }


class GitHubIntegrationView(TenantBoundMixin, APIView):
    """Single read model for the GitHub Integrations screen."""

    permission_classes = [IsOrgMember]

    def get(self, request, org_id):
        repos = list(
            Repository.objects.filter(project__organization_id=request.org.id)
            .order_by("full_name")
        )
        labels = _project_labels(request.org.id)
        installations: dict[int, dict] = {}
        for repo in repos:
            entry = installations.setdefault(
                repo.installation_id, {"installation_id": repo.installation_id, "repository_count": 0}
            )
            entry["repository_count"] += 1
        return Response({
            "configured": github.is_configured(),
            "webhook_configured": github.is_webhook_configured(),
            "installations": sorted(installations.values(), key=lambda i: i["installation_id"]),
            "repositories": RepositorySerializer(
                repos, many=True, context={"project_labels": labels}
            ).data,
        })


class GitHubInstallStartView(TenantBoundMixin, APIView):
    """Return the GitHub App install URL, or a plain 409 when none can exist."""

    permission_classes = [IsOrgMember]

    def post(self, request, org_id):
        if not github.is_configured():
            raise GitHubNotConfigured()
        url = github.installation_url(state=str(request.org.id))
        if not url:
            # An id and key but no slug: GitHub publishes install links by slug only.
            raise GitHubNotConfigured("GitHub App slug is not configured on this server")
        return Response({"url": url})


class RepositoryBranchesView(TenantBoundMixin, APIView):
    """Branches and pull requests need a GitHub client that does not exist yet.

    The screen is given the real state ('sync not run') rather than invented
    branches. Tenancy is still enforced so another org's repository id is a 404.
    """

    permission_classes = [IsOrgMember]

    def get(self, request, org_id, pk):
        from rest_framework.exceptions import NotFound

        repo = Repository.objects.filter(pk=pk, project__organization_id=request.org.id).first()
        if repo is None:
            raise NotFound("Not found")
        return Response({
            "repository_id": str(repo.id),
            "full_name": repo.full_name,
            "default_branch": repo.default_branch,
            "synced": repo.last_synced_at is not None,
            "last_synced_at": repo.last_synced_at,
            "branches": [],
            "pull_requests": [],
            "reason": "Branch and pull request data is not synced: no GitHub client is connected.",
        })


class DeploymentViewSet(TenantBoundMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    """Read-only. Deploys and rollbacks are executed by an approved agent run."""

    permission_classes = [IsOrgMember]
    serializer_class = DeploymentSerializer

    def get_queryset(self):
        qs = Deployment.objects.filter(project__organization_id=self.request.org.id)
        env = self.request.query_params.get("environment")
        st = self.request.query_params.get("status")
        project = self.request.query_params.get("project")
        if env:
            qs = qs.filter(environment=env)
        if st:
            qs = qs.filter(status=st)
        if project:
            qs = qs.filter(project_id=project)
        return qs.order_by("-created_at")

    def get_serializer_class(self):
        return DeploymentDetailSerializer if self.action == "retrieve" else DeploymentSerializer

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["project_labels"] = _project_labels(self.request.org.id)
        if self.action == "retrieve":
            # One query for every repository name in the org: the detail serializer
            # looks the project up in this map instead of querying per row.
            names: dict = {}
            for row in (Repository.objects.filter(project__organization_id=self.request.org.id)
                        .order_by("-full_name").values("project_id", "full_name")):
                names[row["project_id"]] = row["full_name"]
            ctx["repository_names"] = names
        return ctx

    def retrieve(self, request, *args, **kwargs):
        # Cross-tenant ids must be 404, not 403, so ids cannot be enumerated.
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="request-rollback")
    def request_rollback(self, request, *args, **kwargs):
        # Resolve first so another tenant's id is a 404 rather than a 409.
        self.get_object()
        raise DeploymentNotDirect("Deployments are executed by an approved agent run")


class WebhookDeliveryViewSet(TenantBoundMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Deliveries for installations that belong to this org's own repositories."""

    permission_classes = [IsOrgMember]
    serializer_class = WebhookDeliverySerializer

    def get_queryset(self):
        installation_ids = set(
            Repository.objects.filter(project__organization_id=self.request.org.id)
            .values_list("installation_id", flat=True)
        )
        return WebhookDelivery.objects.filter(
            installation_id__in=installation_ids, signature_verified=True,
        ).order_by("-created_at")


# --------------------------------------------------------------------------------
# Webhook receiver: unauthenticated by design, so everything here is defensive.
# --------------------------------------------------------------------------------
def _summarise(event: str, data: dict) -> dict:
    """Pull a few display fields. Never trust shape: every access is guarded."""
    repo = data.get("repository") if isinstance(data.get("repository"), dict) else {}
    install = data.get("installation") if isinstance(data.get("installation"), dict) else {}
    pr = data.get("pull_request") if isinstance(data.get("pull_request"), dict) else {}
    installation_id = install.get("id")
    return {
        "action": str(data.get("action", ""))[:40],
        "installation_id": installation_id if isinstance(installation_id, int) else None,
        "repository_full_name": str(repo.get("full_name", ""))[:200],
        "ref": str(data.get("ref", ""))[:200],
        "commit_sha": str(data.get("after", ""))[:40] if event == "push" else "",
        "pull_request_number": pr.get("number") if isinstance(pr.get("number"), int) and pr.get("number") >= 0 else None,
    }


class GitHubWebhookView(APIView):
    """POST /api/v1/webhooks/github/

    Order matters:
      1. size cap, before the body is read;
      2. a configured secret (otherwise 503: we cannot verify, so we do not accept);
      3. signature over the RAW bytes, in constant time, before any parsing;
      4. a well-formed delivery id;
      5. replay refusal enforced by the database's UNIQUE constraint;
      6. only then parse JSON and record.
    Nothing is executed. The record is proof of receipt, not an instruction.
    """

    authentication_classes: list = []
    permission_classes: list = []
    throttle_classes: list = []

    @classmethod
    def as_view(cls, **initkwargs):
        return csrf_exempt(super().as_view(**initkwargs))

    def post(self, request):
        length = request.META.get("CONTENT_LENGTH")
        if length and length.isdigit() and int(length) > MAX_WEBHOOK_BYTES:
            return Response({"detail": "Payload too large"}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        secret = github.webhook_secret()
        if not secret:
            return Response({"detail": "Webhook receiver is not configured"},
                            status=status.HTTP_503_SERVICE_UNAVAILABLE)

        body: bytes = request.body
        if not github.verify_signature(
            payload=body, signature_header=request.headers.get(github.SIGNATURE_HEADER), secret=secret,
        ):
            logger.warning("github webhook rejected: bad or missing signature")
            return Response({"detail": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

        delivery_id = github.valid_delivery_id(request.headers.get(github.DELIVERY_HEADER))
        if not delivery_id:
            return Response({"detail": "Missing or malformed delivery id"}, status=status.HTTP_400_BAD_REQUEST)

        event = (request.headers.get(github.EVENT_HEADER) or "").strip().lower()[:40]
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            return Response({"detail": "Body is not valid JSON"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(data, dict):
            return Response({"detail": "Body must be a JSON object"}, status=status.HTTP_400_BAD_REQUEST)

        supported = event in github.SUPPORTED_EVENTS
        fields = _summarise(event, data)
        try:
            with transaction.atomic():
                WebhookDelivery.objects.create(
                    delivery_id=delivery_id, event=event,
                    payload_digest=github.payload_digest(body), signature_verified=True,
                    status=WebhookDeliveryStatus.RECEIVED if supported else WebhookDeliveryStatus.IGNORED,
                    summary=f"{event} {fields['action']}".strip()[:300], **fields,
                )
        except IntegrityError:
            # The same X-GitHub-Delivery arrived twice: a replay (or a GitHub retry).
            return Response({"detail": "Delivery already processed"}, status=status.HTTP_409_CONFLICT)

        return Response({"received": True, "event": event, "handled": supported},
                        status=status.HTTP_202_ACCEPTED)
