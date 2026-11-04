"""Read projections for the GitHub and deployment screens.

Two rules applied throughout:

* Only ``*_id`` fields are used to cross a relation. Touching ``obj.project``
  lazily would run a query outside the tenant-bound transaction, where RLS hides
  the parent row and the attribute raises DoesNotExist or returns a stale value.
* Nothing secret is ever included. ``Repository.installation_id`` and
  ``Deployment.config`` can carry credentials or provider internals, so they are
  never exposed directly; config is filtered to display-safe keys only.
"""
from __future__ import annotations

from rest_framework import serializers

from integrations.models import WebhookDelivery
from projects.models import Deployment, Repository

# Deployment.config is a free-form blob written by the executor. Only these keys
# are ever sent to a browser; anything else (tokens, provider payloads) stays out.
SAFE_CONFIG_KEYS = ("provider", "build_log", "commit_message", "duration_seconds",
                    "trigger", "branch", "build_steps")


def _safe_config(config) -> dict:
    if not isinstance(config, dict):
        return {}
    return {key: config[key] for key in SAFE_CONFIG_KEYS if key in config}


class _ProjectLabelMixin(serializers.Serializer):
    """Adds project name/slug from a map the VIEW fetched once, in the bound
    transaction. ``source="project.name"`` would run one lazy query per row (N+1)
    and, outside a bound transaction, RLS would hide the parent entirely."""

    project_id = serializers.UUIDField(read_only=True)
    project_name = serializers.SerializerMethodField()
    project_slug = serializers.SerializerMethodField()

    def _label(self, obj, key: str) -> str:
        labels = self.context.get("project_labels") or {}
        return (labels.get(obj.project_id) or {}).get(key, "")

    def get_project_name(self, obj) -> str:
        return self._label(obj, "name")

    def get_project_slug(self, obj) -> str:
        return self._label(obj, "slug")


class RepositorySerializer(_ProjectLabelMixin, serializers.ModelSerializer):

    class Meta:
        model = Repository
        fields = [
            "id", "project_id", "project_name", "project_slug",
            "provider", "full_name", "default_branch", "is_private",
            "clone_status", "last_synced_at", "created_at",
        ]
        read_only_fields = fields


class DeploymentSerializer(_ProjectLabelMixin, serializers.ModelSerializer):
    approved_by_id = serializers.UUIDField(read_only=True, allow_null=True)
    config = serializers.SerializerMethodField()

    class Meta:
        model = Deployment
        fields = [
            "id", "project_id", "project_name", "project_slug",
            "environment", "status", "commit_sha", "url",
            "approved_by_id", "config", "created_at", "updated_at",
        ]
        read_only_fields = fields

    def get_config(self, obj) -> dict:
        return _safe_config(obj.config)


class DeploymentDetailSerializer(DeploymentSerializer):
    """The detail screen also wants the build log and the repository it came from."""

    build_log = serializers.SerializerMethodField()
    repository_full_name = serializers.SerializerMethodField()

    class Meta(DeploymentSerializer.Meta):
        fields = DeploymentSerializer.Meta.fields + ["build_log", "repository_full_name"]

    def get_build_log(self, obj) -> list[dict]:
        """Deployment has no dedicated log column, so the log lives in config.

        Accepts either a list of ``{at, step, detail}`` entries or a plain list
        of strings; anything else is reported as empty rather than mangled.
        """
        config = obj.config if isinstance(obj.config, dict) else {}
        raw = config.get("build_log")
        if not isinstance(raw, list):
            return []
        entries: list[dict] = []
        for item in raw:
            if isinstance(item, str):
                entries.append({"at": "", "step": item, "detail": ""})
            elif isinstance(item, dict):
                entries.append({
                    "at": str(item.get("at", "")),
                    "step": str(item.get("step", "")),
                    "detail": str(item.get("detail", "")),
                })
        return entries

    def get_repository_full_name(self, obj) -> str:
        names = self.context.get("repository_names") or {}
        return names.get(obj.project_id, "")


class WebhookDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = [
            "id", "delivery_id", "event", "action", "installation_id",
            "repository_full_name", "ref", "commit_sha", "pull_request_number",
            "signature_verified", "status", "summary", "created_at",
        ]
        read_only_fields = fields
