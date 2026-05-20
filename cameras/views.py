from django.db.models import Q
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.viewsets import ModelViewSet
from rest_framework.parsers import MultiPartParser, FormParser
from api.permissions import IsAuthenticatedWithAdminFullAccess, has_full_access
from cameras.models import Camera
from cameras.serializers import CameraSerializer


def _apply_camera_list_filters(queryset, request):
    search_term = (request.query_params.get("search") or "").strip()
    if search_term:
        queryset = queryset.filter(
            Q(name__icontains=search_term)
            | Q(location__icontains=search_term)
            | Q(camera_type__icontains=search_term)
            | Q(status__icontains=search_term)
        )

    allowed_ordering = {
        "name",
        "-name",
        "created_at",
        "-created_at",
        "updated_at",
        "-updated_at",
    }
    ordering = (request.query_params.get("ordering") or "-created_at").strip()
    if ordering not in allowed_ordering:
        ordering = "-created_at"

    return queryset.order_by(ordering)

class CameraViewSet(ModelViewSet):
    """
    Production-ready Camera API for AI Surveillance System.

    Features:
    - User auto-set from request.user
    - Only user's own cameras are visible/editable
    - snapshot, status, last_seen fields are readonly (AI controlled)
    - MultiPartParser/FormParser for snapshot uploads by AI
    """

    serializer_class = CameraSerializer
    permission_classes = [IsAuthenticatedWithAdminFullAccess]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["name", "location", "camera_type", "status", "user__email"]
    ordering_fields = ["name", "created_at", "updated_at", "fps", "status"]
    ordering = ["-created_at"]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Camera.objects.none()

        user = self.request.user

        if not user.is_authenticated:
            return Camera.objects.none()

        if has_full_access(user):
            return Camera.objects.select_related("user")

        return Camera.objects.filter(user=user).select_related("user")

    def perform_create(self, serializer):
        # Auto-set user on creation
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        # Do NOT allow frontend to change the user
        serializer.save()



# cameras/views.py
from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from cameras.models import Camera

class CameraListViewSet(ViewSet):
    permission_classes = [IsAuthenticatedWithAdminFullAccess]

    def list(self, request):
        if has_full_access(request.user):
            cameras = Camera.objects.filter(is_active=True, status='online')
        else:
            cameras = Camera.objects.filter(
                user=request.user,
                is_active=True,
                status='online',
            )
        cameras = _apply_camera_list_filters(cameras, request)
        data = [
            {
                "id": cam.id,
                "name": cam.name,
                "camera_type": cam.camera_type,
                "stream_url": cam.stream_url
            } for cam in cameras
        ]
        return Response(data)
    
