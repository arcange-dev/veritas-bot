from __future__ import annotations

from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.services import record_audit
from core.permissions import IsOrgAdmin, IsOrgMember, IsOrgWriter
from core.rls import TenantBoundMixin
from core.tenancy import for_org
from projects.models import Project
from projects.serializers import ProjectSerializer


class ProjectViewSet(TenantBoundMixin, viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    filterset_fields = ["execution_preference"]
    search_fields = ["name", "slug"]

    def get_permissions(self):
        if self.request.method in {"GET", "HEAD", "OPTIONS"}:
            return [IsOrgMember()]
        if self.action in {"destroy"}:
            return [IsOrgAdmin()]            # permanent deletion is an admin decision
        return [IsOrgWriter()]

    def get_queryset(self):
        qs = for_org(Project.objects.select_related("created_by"), self.request.org)
        # Archived projects are hidden unless asked for; a direct id still resolves
        # so an archived project can be opened, restored or deleted.
        flag = self.request.query_params.get("archived")
        if self.action == "list":
            if flag in {"1", "true", "True"}:
                qs = qs.filter(archived_at__isnull=False)
            elif flag != "all":
                qs = qs.filter(archived_at__isnull=True)
        return qs.order_by("-created_at")

    def perform_destroy(self, instance):
        record_audit(action="project.deleted", organization=self.request.org, actor=self.request.user,
                     target_type="project", target_id=str(instance.id), metadata={"name": instance.name})
        instance.delete()

    @action(detail=True, methods=["post"])
    def archive(self, request, *args, **kwargs):
        project = self.get_object()
        if project.archived_at is None:
            project.archived_at = timezone.now()
            project.save(update_fields=["archived_at", "updated_at"])
            record_audit(action="project.archived", organization=request.org, actor=request.user,
                         target_type="project", target_id=str(project.id))
        return Response(self.get_serializer(project).data)

    @action(detail=True, methods=["post"])
    def unarchive(self, request, *args, **kwargs):
        project = self.get_object()
        if project.archived_at is not None:
            project.archived_at = None
            project.save(update_fields=["archived_at", "updated_at"])
            record_audit(action="project.unarchived", organization=request.org, actor=request.user,
                         target_type="project", target_id=str(project.id))
        return Response(self.get_serializer(project).data)
