import base64
from unittest.mock import Mock, patch

import cv2
import numpy as np
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from alert.models import Alert
from cameras.models import Camera
from detection.notifications import send_suspicious_detection_email
from users.models import User


def _base64_test_image():
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    success, buffer_jpg = cv2.imencode(".jpg", frame)
    if not success:
        raise AssertionError("Failed to create test image")
    encoded = base64.b64encode(buffer_jpg.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="alerts@example.com",
    SUSPICIOUS_EMAIL_ENABLED=True,
)
class SuspiciousEmailNotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="owner@example.com", password="pass1234")
        self.camera = Camera.objects.create(
            user=self.user,
            name="Front Door",
            location="Lobby",
            camera_type="webcam",
            stream_url="rtsp://front-door",
        )

    @patch("detection.notifications.requests.get")
    def test_email_contains_frame_link_and_attachment(self, mock_get):
        mock_response = Mock()
        mock_response.content = b"fake-jpeg-bytes"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        alert = Alert.objects.create(
            user=self.user,
            camera=self.camera,
            alert_type="suspicious",
            confidence=0.95,
            frame_url="https://example.com/suspicious-frame.jpg",
        )

        result = send_suspicious_detection_email(alert)

        self.assertTrue(result)
        self.assertEqual(len(mail.outbox), 1)
        email = mail.outbox[0]
        self.assertIn("Front Door", email.subject)
        self.assertIn("https://example.com/suspicious-frame.jpg", email.body)
        self.assertEqual(len(email.alternatives), 1)
        self.assertEqual(email.attachments[0][0], "suspicious-frame.jpg")

    @patch("detection.notifications.requests.get")
    @patch("detection.notifications.get_connection")
    def test_email_network_unreachable_stops_retries(self, mock_get_connection, mock_get):
        mock_response = Mock()
        mock_response.content = b"fake-jpeg-bytes"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        backend = Mock()
        backend.send_messages.side_effect = OSError(101, "Network is unreachable")
        mock_get_connection.return_value = backend

        alert = Alert.objects.create(
            user=self.user,
            camera=self.camera,
            alert_type="suspicious",
            confidence=0.95,
            frame_url="https://example.com/suspicious-frame.jpg",
        )

        result = send_suspicious_detection_email(alert)

        self.assertFalse(result)
        self.assertEqual(backend.send_messages.call_count, 1)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="alerts@example.com",
    SUSPICIOUS_EMAIL_ENABLED=True,
)
class DetectionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="operator@example.com", password="pass1234")
        self.camera = Camera.objects.create(
            user=self.user,
            name="Warehouse Cam",
            location="Gate 1",
            camera_type="webcam",
            stream_url="rtsp://warehouse-cam",
        )
        self.client.force_authenticate(user=self.user)

    @patch("detection.notifications.requests.get")
    @patch("detection.views._upload_frame_url")
    @patch("detection.views.predict_frame_multi15")
    def test_detection_api_saves_frame_url_and_sends_email(
        self,
        mock_predict,
        mock_upload_frame_url,
        mock_get,
    ):
        mock_predict.return_value = ("Suspicious", 0.93)
        mock_upload_frame_url.return_value = "https://example.com/api-frame.jpg"
        mock_response = Mock()
        mock_response.content = b"fake-jpeg-bytes"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        response = self.client.post(
            "/api/detection/",
            {
                "image": _base64_test_image(),
                "camera_id": self.camera.id,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["label"], "Suspicious")
        self.assertEqual(response.data["frame_url"], "https://example.com/api-frame.jpg")

        alert = Alert.objects.get(camera=self.camera, user=self.user)
        self.assertEqual(alert.frame_url, "https://example.com/api-frame.jpg")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("https://example.com/api-frame.jpg", mail.outbox[0].body)
