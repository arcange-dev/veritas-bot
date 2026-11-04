from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.errors import InvalidState
from core.permissions import IsOrgMember, IsOrgWriter
from core.tenancy import for_org, scoped_or_404
from core.rls import TenantBoundMixin
from orchestration import services
from orchestration.models import AgentRun, ApprovalRequest
from orchestration.serializers import (
    ApprovalSerializer, DecisionSerializer, RunCreateSerializer,
    RunDetailSerializer, RunSerializer,
)
from orchestration.tasks import enqueue_run
from projects.models import Project


def _conflict(exc: Exception) -> InvalidState:
    return InvalidState(str(exc))


class RunViewSet(TenantBoundMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                 viewsets.GenericViewSet):
    """Runs are created through `create` below, never PATCHed: the lifecycle
    service is the only thing allowed to move a run between states."""

    filterset_fields = ["status", "project"]

    def get_permissions(self):
        if self.request.method in {"GET", "HEAD", "OPTIONS"}:
            return [IsOrgMember()]
        return [IsOrgWriter()]

    def get_queryset(self):
        return for_org(AgentRun.objects.all(), self.request.org).order_by("-created_at")

    def get_serializer_class(self):
        return RunDetailSerializer if self.action == "retrieve" else RunSerializer

    def create(self, request, *args, **kwargs):
        body = RunCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data

        # The project must belong to the caller's org: a UUID from another tenant is a 404.
        project = scoped_or_404(Project.objects.all(), request.org, id=data["project"])
        run = services.create_run(
            project=project, profile=request.user, objective=data["objective"],
            execution_target=data["execution_target"],
            cost_cap_usd=data.get("cost_cap_usd"),
        )
        services.start(run)
        enqueue_run(str(run.id), str(request.org.id), str(request.user.pk))
        run.refresh_from_db()
        return Response(RunSerializer(run).data, status=status.HTTP_201_CREATED)

    def _control(self, request, fn):
        run = self.get_object()
        try:
            run = fn(run, request.user)
        except services.InvalidTransition as exc:
            raise _conflict(exc) from None
        return Response(RunSerializer(run).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, *args, **kwargs):
        return self._control(request, services.cancel)

    @action(detail=True, methods=["post"])
    def pause(self, request, *args, **kwargs):
        return self._control(request, services.pause)

    @action(detail=True, methods=["post"])
    def resume(self, request, *args, **kwargs):
        response = self._control(request, services.resume)
        enqueue_run(str(self.get_object().id), str(request.org.id), str(request.user.pk))
        return response


class ApprovalViewSet(TenantBoundMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                      viewsets.GenericViewSet):
    serializer_class = ApprovalSerializer
    filterset_fields = ["state", "run"]

    def get_permissions(self):
        if self.request.method in {"GET", "HEAD", "OPTIONS"}:
            return [IsOrgMember()]
        return [IsOrgWriter()]

    def get_queryset(self):
        # Tenancy flows through the run: an approval has no org column of its own.
        return ApprovalRequest.objects.filter(
            run__organization=self.request.org
        ).order_by("-created_at")

    @action(detail=True, methods=["post"])
    def decide(self, request, *args, **kwargs):
        approval = self.get_object()
        body = DecisionSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            decided = services.decide(
                approval, approve=body.validated_data["approve"], actor=request.user,
                note=body.validated_data.get("note", ""),
            )
        except services.ApprovalError as exc:
            raise _conflict(exc) from None
        return Response(ApprovalSerializer(decided).data)
