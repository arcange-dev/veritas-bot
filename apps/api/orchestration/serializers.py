from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from orchestration.models import AgentRun, AgentStep, ApprovalRequest

MAX_COST_CAP = Decimal("100")


class StepSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentStep
        fields = ["id", "sequence", "agent_kind", "title", "status", "depends_on",
                  "write_scope", "error", "started_at", "finished_at"]
        read_only_fields = fields


class ApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRequest
        fields = ["id", "run", "action_type", "summary", "payload", "state",
                  "expires_at", "decided_at", "decision_note"]
        read_only_fields = fields


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRun
        fields = ["id", "project", "objective", "status", "execution_target", "plan",
                  "cost_usd", "cost_cap_usd", "iterations", "error_code",
                  "started_at", "finished_at", "created_at"]
        read_only_fields = [f for f in fields if f not in {"project", "objective"}]


class RunDetailSerializer(RunSerializer):
    steps = StepSerializer(many=True, read_only=True)
    pending_approvals = serializers.SerializerMethodField()

    class Meta(RunSerializer.Meta):
        fields = RunSerializer.Meta.fields + ["steps", "pending_approvals"]
        read_only_fields = fields

    def get_pending_approvals(self, run: AgentRun) -> list[dict]:
        pending = run.approvals.filter(state="pending")
        return ApprovalSerializer(pending, many=True).data


class RunCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()
    objective = serializers.CharField(min_length=3, max_length=8000, trim_whitespace=True)
    execution_target = serializers.ChoiceField(choices=["cloud", "local"], default="cloud")
    cost_cap_usd = serializers.DecimalField(
        max_digits=12, decimal_places=6, required=False,
        min_value=Decimal("0.01"), max_value=MAX_COST_CAP,
    )


class DecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True, max_length=1000)
