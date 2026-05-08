from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate

from cameras.models import Camera
from cameras.serializers import CameraSerializer
from users.models import User


class CameraSerializerTests(APITestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = User.objects.create_user(email="owner@example.com", password="pass1234")
        self.camera = Camera.objects.create(
            user=self.user,
            name="Front Door",
            location="Lobby",
            camera_type="webcam",
            stream_url="rtsp://front-door",
        )

    def test_update_keeps_same_name_valid(self):
        request = self.factory.patch(f"/api/cameras/{self.camera.pk}/", {"name": "Front Door"})
        force_authenticate(request, user=self.user)
        serializer = CameraSerializer(
            instance=self.camera,
            data={"name": "Front Door"},
            partial=True,
            context={"request": request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
