from __future__ import annotations

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audit.services import record_audit
from core.permissions import IsOrgAdmin, IsOrgMember
from core.tenancy import for_org, scoped_or_404
from core.rls import TenantBoundMixin
from providers.crypto import encrypt_secret
from providers.models import CredentialStatus, ProviderCredential
from providers.probes import probe
from providers.serializers import CredentialSerializer


class CredentialViewSet(TenantBoundMixin, viewsets.ModelViewSet):
    """BYOK credentials. Admins write, members read the safe projection."""

    serializer_class = CredentialSerializer
    http_method_names = ["get", "post", "delete", "patch", "head", "options"]

    def get_permissions(self):
        if self.request.method in {"GET", "HEAD", "OPTIONS"}:
            return [IsOrgMember()]
        return [IsOrgAdmin()]

    def get_queryset(self):
        return for_org(ProviderCredential.objects.all(), self.request.org).order_by(
            "-created_at"
        )

    def perform_create(self, serializer):
        api_key = serializer.validated_data.pop("api_key")
        base_url = serializer.validated_data.get("base_url", "")
        token, key_id = encrypt_secret(api_key, base_url)
        credential = serializer.save(
            organization=self.request.org,
            created_by=self.request.user,
            secret_encrypted=token,
            key_id=key_id,
            last4=api_key[-4:],
        )
        record_audit(
            action="credential.created",
            organization=self.request.org,
            actor=self.request.user,
            target_type="credential",
            target_id=str(credential.id),
            metadata={"provider": credential.provider},
        )

    @action(detail=True, methods=["post"], url_path="test",
            permission_classes=[IsOrgAdmin])
    def test(self, request, org_id=None, pk=None):
        """Validate a stored credential. Never echoes the provider's raw body."""
        credential = scoped_or_404(ProviderCredential.objects.all(), request.org, pk=pk)
        from providers.crypto import decrypt_secret

        secret = decrypt_secret(credential.secret_encrypted, credential.key_id)
        result = probe(credential.provider, secret["api_key"],
                       secret["base_url"] or credential.base_url)
        credential.status = (CredentialStatus.VALID if result.ok
                             else CredentialStatus.INVALID)
        credential.last_error_code = "" if result.ok else result.error_code
        from django.utils import timezone

        credential.last_validated_at = timezone.now()
        credential.save(update_fields=["status", "last_error_code", "last_validated_at",
                                       "updated_at"])
        record_audit(
            action="credential.validated", organization=request.org, actor=request.user,
            target_type="credential", target_id=str(credential.id),
            metadata={"ok": result.ok, "error_code": credential.last_error_code},
        )
        return Response(
            {"ok": result.ok, "status": credential.status,
             "error_code": credential.last_error_code,
             "detail": result.detail, "model_count": result.model_count},
            status=status.HTTP_200_OK,
        )
