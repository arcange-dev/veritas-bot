from __future__ import annotations

from rest_framework import serializers

from execution.models import ExecutionSession, LocalRunnerDevice


class DeviceSerializer(serializers.ModelSerializer):
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = LocalRunnerDevice
        fields = [
            "id", "name", "os", "arch", "runner_version", "paired_at",
            "last_seen_at", "revoked_at", "workspace_roots", "is_online", "is_active",
        ]
        read_only_fields = fields

    def get_is_online(self, obj) -> bool:
        from execution.presence import is_online

        return obj.revoked_at is None and is_online(str(obj.id))


class ClaimSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=16)
    fingerprint = serializers.CharField(min_length=16, max_length=64)
    name = serializers.CharField(max_length=120)
    os = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    arch = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")
    workspace_roots = serializers.ListField(
        child=serializers.CharField(max_length=400), required=False, max_length=20,
        default=list,
    )


class SessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExecutionSession
        fields = [
            "id", "run", "backend", "status", "device", "external_id",
            "workspace_path", "preview_url", "expires_at", "last_activity_at",
        ]
        read_only_fields = fields
