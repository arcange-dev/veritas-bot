from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """GitHub integration, webhook inbox and the read models for deployments.

    This app owns no project/repository/deployment data: those rows live in
    `projects` and are read here, always tenant-scoped through
    `project__organization_id`.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "integrations"
    verbose_name = "Integrations"
