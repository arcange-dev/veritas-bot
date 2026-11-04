from __future__ import annotations

from django.db import models

from core.models import OrgScopedModel, TimeStampedModel, UUIDModel


class Project(OrgScopedModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80)
    description = models.TextField(blank=True)
    default_branch = models.CharField(max_length=120, default="main")
    execution_preference = models.CharField(
        max_length=20,
        choices=[("local", "Local runner"), ("cloud", "Cloud sandbox")],
        default="cloud",
    )
    created_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, related_name="projects"
    )
    # Archive is a soft state with a timestamp (not a boolean) so the UI can say
    # when, and so it is reversible. Deleting is a separate, permanent action.
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "projects_project"
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "slug"], name="uniq_project_org_slug"
            )
        ]
        indexes = [models.Index(fields=["organization", "-created_at"], name="idx_project_org")]

    def __str__(self) -> str:
        return f"{self.organization_id}/{self.slug}"


class Repository(UUIDModel, TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="repositories")
    provider = models.CharField(max_length=20, default="github")
    installation_id = models.BigIntegerField()
    full_name = models.CharField(max_length=200)          # owner/repo
    default_branch = models.CharField(max_length=120, default="main")
    is_private = models.BooleanField(default=True)
    clone_status = models.CharField(
        max_length=20,
        choices=[("pending", "Pending"), ("cloning", "Cloning"),
                 ("ready", "Ready"), ("failed", "Failed")],
        default="pending",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "projects_repository"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "full_name"], name="uniq_repository_project_fullname"
            )
        ]


class RepositoryIndex(UUIDModel, TimeStampedModel):
    """A bounded summary so agents read an index, not an entire repository."""

    repository = models.OneToOneField(
        Repository, on_delete=models.CASCADE, related_name="index"
    )
    file_count = models.PositiveIntegerField(default=0)
    total_bytes = models.BigIntegerField(default=0)
    languages = models.JSONField(default=dict)
    tree = models.JSONField(default=list)
    summary = models.TextField(blank=True)
    truncated = models.BooleanField(default=False)


class Deployment(UUIDModel, TimeStampedModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="deployments")
    environment = models.CharField(
        max_length=20, choices=[("preview", "Preview"), ("staging", "Staging"),
                                ("production", "Production")],
        default="preview",
    )
    status = models.CharField(
        max_length=20,
        choices=[("draft", "Draft"), ("pending_approval", "Pending approval"),
                 ("approved", "Approved"), ("deployed", "Deployed"),
                 ("failed", "Failed"), ("rolled_back", "Rolled back")],
        default="draft",
    )
    commit_sha = models.CharField(max_length=40, blank=True)
    url = models.URLField(blank=True)
    config = models.JSONField(default=dict)
    approved_by = models.ForeignKey(
        "identity.Profile", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "projects_deployment"
