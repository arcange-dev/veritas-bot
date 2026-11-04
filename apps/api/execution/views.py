from __future__ import annotations

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from audit.services import record_audit
from core.permissions import IsOrgAdmin, IsOrgMember
from core.tenancy import for_org, scoped_or_404
from core.rls import TenantBoundMixin
from execution import pairing
from execution.models import LocalRunnerDevice
from execution.serializers import ClaimSerializer, DeviceSerializer


class PairingClaimThrottle(SimpleRateThrottle):
    """Paired devices are the crown jewels; a code must not be brute-forceable."""

    scope = "pairing_claim"
    rate = "20/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class DeviceViewSet(TenantBoundMixin, 
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    serializer_class = DeviceSerializer
    permission_classes = [IsOrgMember]

    def get_queryset(self):
        return for_org(LocalRunnerDevice.objects.all(), self.request.org).order_by(
            "-paired_at"
        )

    @action(detail=False, methods=["post"], url_path="pairing-codes",
            permission_classes=[IsOrgAdmin])
    def pairing_codes(self, request, org_id=None):
        code, record = pairing.mint_code(request.org, request.user)
        record_audit(
            action="runner.pairing_code_minted",
            organization=request.org,
            actor=request.user,
            target_type="pairing_code",
            target_id=str(record.id),
        )
        return Response(
            {
                "code": code,
                "expires_at": record.expires_at,
                "instructions": "Run `superagent-runner pair <code>` on the machine.",
            },
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], permission_classes=[IsOrgAdmin])
    def revoke(self, request, org_id=None, pk=None):
        device = scoped_or_404(LocalRunnerDevice.objects.all(), request.org, pk=pk)
        pairing.revoke(device)
        record_audit(
            action="runner.revoked",
            organization=request.org,
            actor=request.user,
            target_type="runner_device",
            target_id=str(device.id),
        )
        return Response(DeviceSerializer(device).data)


class RunnerClaimView(APIView):
    """Unauthenticated by design: the pairing code *is* the credential."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    throttle_classes = [PairingClaimThrottle]

    def post(self, request):
        serializer = ClaimSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            device, token = pairing.claim_code(
                code=payload["code"],
                fingerprint=payload["fingerprint"],
                name=payload["name"],
                os_name=payload.get("os", ""),
                arch=payload.get("arch", ""),
                workspace_roots=payload.get("workspace_roots") or [],
            )
        except pairing.PairingError as exc:
            return Response(
                {"error": {"code": "invalid_pairing_code", "detail": str(exc)}},
                status=status.HTTP_400_BAD_REQUEST,
            )

        record_audit(
            action="runner.paired",
            organization=device.organization,
            actor_type="system",
            target_type="runner_device",
            target_id=str(device.id),
            metadata={"os": device.os, "arch": device.arch},
        )
        return Response(
            {
                "device_id": str(device.id),
                "organization_id": str(device.organization_id),
                "token": token,
                "token_ttl_seconds": 900,
                "ws_path": f"/ws/runner/?device={device.id}&token=<token>",
            },
            status=status.HTTP_201_CREATED,
        )
