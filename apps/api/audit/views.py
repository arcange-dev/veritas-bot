"""Notifications (per person) and the audit log (admins only).

A notification belongs to ONE member of the org, not to the org. Filtering by
organization alone would let any member read their colleagues' notifications, so
every query here also filters by the acting profile.
"""
from __future__ import annotations

from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from audit.models import AuditLog, Notification
from audit.serializers import AuditLogSerializer, NotificationSerializer
from core.permissions import IsOrgAdmin, IsOrgMember
from core.rls import TenantBoundMixin


class NotificationViewSet(TenantBoundMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsOrgMember]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(
            organization_id=self.request.org.id, profile_id=self.request.membership.profile_id,
        )
        if self.request.query_params.get("unread") in {"1", "true", "True"}:
            qs = qs.filter(read_at__isnull=True)
        return qs.order_by("-created_at")

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        unread = Notification.objects.filter(
            organization_id=request.org.id, profile_id=request.membership.profile_id, read_at__isnull=True,
        ).count()
        if isinstance(response.data, dict):
            response.data["unread_count"] = unread
        return response

    @action(detail=True, methods=["post"])
    def read(self, request, *args, **kwargs):
        row = self.get_queryset().filter(pk=kwargs["pk"]).first()
        if row is None:
            raise NotFound("Not found")          # someone else's notification is a 404, not a 403
        if row.read_at is None:
            row.read_at = timezone.now()
            row.save(update_fields=["read_at"])
        return Response(NotificationSerializer(row).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request, *args, **kwargs):
        updated = Notification.objects.filter(
            organization_id=request.org.id, profile_id=request.membership.profile_id,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        return Response({"marked_read": updated})

    @action(detail=False, methods=["post"], url_path="unread")
    def mark_unread(self, request, *args, **kwargs):
        """Undo for 'mark as read' (the design offers 'Undo mark as read')."""
        ids = request.data.get("ids") if isinstance(request.data, dict) else None
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > 200:
            return Response({"detail": "ids must be a list of at most 200 ids"}, status=400)
        updated = Notification.objects.filter(
            organization_id=request.org.id, profile_id=request.membership.profile_id, pk__in=ids,
        ).update(read_at=None)
        return Response({"marked_unread": updated})


class AuditLogViewSet(TenantBoundMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Admins only: the log records who did what, including other members."""

    permission_classes = [IsOrgAdmin]
    serializer_class = AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.filter(organization_id=self.request.org.id)
        action_filter = self.request.query_params.get("action")
        if action_filter:
            qs = qs.filter(action=action_filter)
        return qs.order_by("-created_at")
