"""Dashboard summary: real numbers from real tables, nothing estimated or invented."""
from __future__ import annotations

from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from billing.models import UsageRecord
from core.permissions import IsOrgMember
from core.rls import TenantBoundMixin
from orchestration.models import AgentRun, ApprovalRequest, RunStatus
from projects.models import Project

ACTIVE_STATUSES = [RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED, RunStatus.WAITING_APPROVAL]


def month_start(now=None):
    """First instant of the current calendar month in UTC.

    A rolling 30 days would disagree with the 'this month' label, and a monthly
    spend cap is a calendar-month concept.
    """
    now = now or timezone.now()
    return now.astimezone(dt_timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def dollars(value) -> str:
    """Exact decimal string with six places, matching the rest of the API."""
    return f"{Decimal(value or 0):.6f}"


class DashboardSummaryView(TenantBoundMixin, APIView):
    permission_classes = [IsOrgMember]

    def get(self, request, org_id):
        org_id = request.org.id
        runs = AgentRun.objects.filter(organization_id=org_id)
        by_status = {row["status"]: row["n"] for row in runs.values("status").annotate(n=Count("id"))}
        spend = UsageRecord.objects.filter(
            organization_id=org_id, created_at__gte=month_start(),
        ).aggregate(total=Sum("cost_usd"))["total"]

        recent = list(
            runs.order_by("-created_at").values("id", "objective", "status", "cost_usd", "project_id", "created_at")[:8]
        )
        return Response({
            "project_count": Project.objects.filter(organization_id=org_id).count(),
            "active_runs": sum(by_status.get(s, 0) for s in ACTIVE_STATUSES),
            "runs_by_status": by_status,
            # Approvals are tenant-scoped through their run (no organization column).
            "pending_approvals": ApprovalRequest.objects.filter(
                run__organization_id=org_id, state="pending").count(),
            "spend_this_month_usd": dollars(spend),
            "month_started_at": month_start(),
            "recent_runs": [
                {**r, "id": str(r["id"]), "project_id": str(r["project_id"]), "cost_usd": dollars(r["cost_usd"])}
                for r in recent
            ],
        })
