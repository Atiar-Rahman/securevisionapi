from rest_framework.viewsets import ModelViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from cameras.models import Camera
from cameras.serializers import CameraSerializer

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
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return Camera.objects.none()

        user = self.request.user

        if not user.is_authenticated:
            return Camera.objects.none()

        return Camera.objects.filter(user=user).order_by('-created_at')

    def perform_create(self, serializer):
        # Auto-set user on creation
        serializer.save(user=self.request.user)

    def perform_update(self, serializer):
        # Do NOT allow frontend to change the user
        serializer.save()



# cameras/views.py
from rest_framework.viewsets import ViewSet
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from cameras.models import Camera

class CameraListViewSet(ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        cameras = Camera.objects.filter(user=request.user, is_active=True,status='online').order_by('-created_at')
        data = [
            {
                "id": cam.id,
                "name": cam.name,
                "camera_type": cam.camera_type,
                "stream_url": cam.stream_url
            } for cam in cameras
        ]
        return Response(data)
    

