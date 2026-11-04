"""Identity mirrors Supabase Auth. Supabase owns credentials; we own profiles,
organizations and memberships. There is no second password store."""
from __future__ import annotations

from django.db import models

from core.models import OrgScopedModel, TimeStampedModel, UUIDModel


class Profile(UUIDModel, TimeStampedModel):
    """One row per Supabase user. Created lazily on first authenticated request."""

    supabase_user_id = models.UUIDField(unique=True, db_index=True)
    email = models.EmailField(db_index=True)
    display_name = models.CharField(max_length=120, blank=True)
    avatar_url = models.URLField(blank=True)
    is_platform_admin = models.BooleanField(
        default=False,
        help_text="Platform operator. Can read audit/health, never plaintext credentials.",
    )
    last_seen_at = models.DateTimeField(null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)

    # DRF and Django's auth contract: a real Profile is always authenticated.
    # Anonymous requests carry AnonymousUser, which reports False.
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    class Meta:
        db_table = "identity_profile"
        indexes = [models.Index(fields=["email"], name="idx_profile_email")]

    def __str__(self) -> str:
        return f"{self.email} ({self.id})"


class Plan(models.TextChoices):
    FREE = "free", "Free"
    TEAM = "team", "Team"
    ENTERPRISE = "enterprise", "Enterprise"


class Organization(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, unique=True)
    plan = models.CharField(
        max_length=20, choices=Plan.choices, default=Plan.FREE
    )
    monthly_spend_cap_usd = models.DecimalField(max_digits=10, decimal_places=2, default=50)
    max_task_cost_usd = models.DecimalField(max_digits=10, decimal_places=2, default=5)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        Profile, on_delete=models.PROTECT, related_name="created_organizations"
    )

    class Meta:
        db_table = "identity_organization"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"
    ADMIN = "admin", "Admin"
    MEMBER = "member", "Member"
    VIEWER = "viewer", "Viewer"


class Membership(UUIDModel, TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="memberships"
    )
    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(
        max_length=20, choices=MembershipRole.choices, default=MembershipRole.MEMBER
    )
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(
        Profile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sent_invitations",
    )

    class Meta:
        db_table = "identity_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "profile"], name="uniq_membership_org_profile"
            ),
            models.CheckConstraint(
                check=models.Q(role__in=["owner", "admin", "member", "viewer"]),
                name="ck_membership_role",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "is_active"], name="idx_membership_profile_active"),
        ]

    def __str__(self) -> str:
        return f"{self.profile_id} in {self.organization_id} as {self.role}"


class Invitation(UUIDModel, TimeStampedModel):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="invitations"
    )
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=MembershipRole.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(Profile, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "identity_invitation"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "email"], name="uniq_invitation_org_email"
            )
        ]
