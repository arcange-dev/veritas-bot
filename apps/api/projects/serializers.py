from __future__ import annotations

from django.utils.text import slugify
from rest_framework import serializers

from projects.models import Project


class ProjectSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(max_length=80, required=False)
    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ["id", "name", "slug", "description", "default_branch",
                  "execution_preference", "archived_at", "is_archived", "created_at", "updated_at"]
        read_only_fields = ["id", "archived_at", "is_archived", "created_at", "updated_at"]

    def get_is_archived(self, obj) -> bool:
        return obj.archived_at is not None

    def validate(self, attrs):
        # A slug is a URL: renaming a project must never change it implicitly.
        # It is derived from the name only when a project is CREATED.
        if self.instance is None:
            if not attrs.get("slug") and attrs.get("name"):
                attrs["slug"] = slugify(attrs["name"])[:80]
            if not attrs.get("slug"):
                raise serializers.ValidationError({"name": "Use letters or numbers in the project name."})

        slug = attrs.get("slug")
        if slug:
            request = self.context["request"]
            clash = Project.objects.filter(organization_id=request.org.id, slug=slug)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                # Field-level 400 (the design's "Choose a unique project name"), not a 500.
                raise serializers.ValidationError({"name": "A project with this name already exists."})
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        return Project.objects.create(
            organization=request.org, created_by=request.user, **validated_data
        )
