"""Run state that must survive restarts. LangGraph checkpoints live beside this,
but these rows are what the UI lists and what the audit trail references."""
from __future__ import annotations

from django.db import models

from core.models import OrgScopedModel, TimeStampedModel, UUIDModel


class AgentKind(models.TextChoices):
    ORCHESTRATOR = "orchestrator", "Orchestrator"
    ANALYST = "analyst", "Project analyst"
    ARCHITECT = "architect", "Software architect"
    FRONTEND = "frontend", "Frontend engineer"
    BACKEND = "backend", "Backend engineer"
    DATABASE = "database", "Database engineer"
    INTEGRATION = "integration", "Integration engineer"
    QA = "qa", "QA engineer"
    SECURITY = "security", "Security engineer"
    DEVOPS = "devops", "DevOps engineer"


class AgentProfile(OrgScopedModel):
    """Per-org configuration of a specialist. Model choice is BYOK-resolved."""

    kind = models.CharField(max_length=30, choices=AgentKind.choices)
    display_name = models.CharField(max_length=120)
    system_prompt = models.TextField(blank=True)
    model_provider = models.CharField(max_length=40, blank=True)
    model_id = models.CharField(max_length=160, blank=True)
    fallback_provider = models.CharField(max_length=40, blank=True)
    fallback_model_id = models.CharField(max_length=160, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=2, default=0.20)
    max_tokens = models.PositiveIntegerField(default=8192)
    allowed_tools = models.JSONField(default=list, blank=True)
    required_capabilities = models.JSONField(default=list, blank=True)
    is_enabled = models.BooleanField(default=True)

    class Meta:
        db_table = "orchestration_agent_profile"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind"], name="uniq_agent_profile_org_kind"
            )
        ]


class Conversation(OrgScopedModel):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="conversations", null=True
    )
    title = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, related_name="conversations"
    )

    class Meta:
        db_table = "orchestration_conversation"
        indexes = [models.Index(fields=["organization", "-created_at"], name="idx_conv_org")]


class MessageRole(models.TextChoices):
    USER = "user", "User"
    ASSISTANT = "assistant", "Assistant"
    SYSTEM = "system", "System"
    TOOL = "tool", "Tool"


class Message(UUIDModel, TimeStampedModel):
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=MessageRole.choices)
    content = models.TextField(blank=True)
    tool_calls = models.JSONField(default=list, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    author_profile = models.ForeignKey(
        "identity.Profile", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    agent_kind = models.CharField(max_length=30, blank=True)

    class Meta:
        db_table = "orchestration_message"
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="idx_message_conv_created")
        ]


class RunStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    PAUSED = "paused", "Paused"
    WAITING_APPROVAL = "waiting_approval", "Waiting for approval"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    NEEDS_REVIEW = "needs_review", "Needs review"


class AgentRun(OrgScopedModel):
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="runs"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    objective = models.TextField()
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.QUEUED, db_index=True
    )
    execution_target = models.CharField(
        max_length=20,
        choices=[("local", "Local runner"), ("cloud", "Cloud sandbox")],
        default="cloud",
    )
    plan = models.JSONField(default=list, blank=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    cost_cap_usd = models.DecimalField(max_digits=12, decimal_places=6, default=5)
    iterations = models.PositiveSmallIntegerField(default=0)
    error_code = models.CharField(max_length=60, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, related_name="runs"
    )

    class Meta:
        db_table = "orchestration_run"
        indexes = [
            models.Index(fields=["organization", "-created_at"], name="idx_run_org_created"),
            models.Index(fields=["status"], name="idx_run_status"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(cost_usd__gte=0), name="ck_run_cost_non_negative"
            )
        ]


class StepStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    BLOCKED = "blocked", "Blocked"


class AgentStep(UUIDModel, TimeStampedModel):
    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    agent_kind = models.CharField(max_length=30, choices=AgentKind.choices)
    sequence = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=StepStatus.choices, default=StepStatus.PENDING
    )
    depends_on = models.JSONField(default=list, blank=True)     # step ids
    write_scope = models.JSONField(default=list, blank=True)    # file globs
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orchestration_step"
        constraints = [
            models.UniqueConstraint(fields=["run", "sequence"], name="uniq_step_run_sequence")
        ]
        indexes = [
            models.Index(fields=["run", "status"], name="idx_step_run_status"),
            models.Index(fields=["run", "sequence"], name="idx_step_run_sequence_order"),
        ]


class ApprovalState(models.TextChoices):
    PENDING = "pending", "Pending"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EXPIRED = "expired", "Expired"


class ApprovalRequest(UUIDModel, TimeStampedModel):
    """A gate between a planned destructive action and its execution.

    `payload_hash` is recomputed at execution time: an approved action that has
    since changed is rejected, which closes the replay hole.
    """

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="approvals")
    step = models.ForeignKey(
        AgentStep, on_delete=models.CASCADE, related_name="approvals", null=True, blank=True
    )
    action_type = models.CharField(max_length=60)
    summary = models.TextField()
    payload = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    state = models.CharField(
        max_length=20, choices=ApprovalState.choices, default=ApprovalState.PENDING
    )
    expires_at = models.DateTimeField()
    decided_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        db_table = "orchestration_approval"
        indexes = [
            models.Index(fields=["run", "state"], name="idx_approval_run_state"),
        ]
