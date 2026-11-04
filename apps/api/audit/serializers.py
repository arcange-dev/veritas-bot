from __future__ import annotations

from rest_framework import serializers

from audit.models import AuditLog, Notification


class NotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "link", "read_at", "is_read", "created_at"]
        read_only_fields = fields

    def get_is_read(self, obj) -> bool:
        return obj.read_at is not None


class AuditLogSerializer(serializers.ModelSerializer):
    actor_id = serializers.UUIDField(source="actor_profile_id", read_only=True, allow_null=True)

    class Meta:
        model = AuditLog
        # ip_hash is deliberately omitted: it is a privacy-sensitive derivative that no screen needs.
        fields = ["id", "created_at", "actor_id", "actor_type", "action", "target_type",
                  "target_id", "metadata", "request_id"]
        read_only_fields = fields
