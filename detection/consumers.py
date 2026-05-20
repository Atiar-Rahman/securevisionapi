import json
import base64
import cv2
import numpy as np
from django.utils import timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async

from detection.ml.pridict_gray import (
    predict_frame14,
    predict_frame_multi,
    predict_frame_multi15,
)
from detection.ml.predict3dcnn import predict_frame_multi3d

from alert.models import Alert
from cameras.models import Camera
from detection.cloudinary_utils import upload_frame_to_cloudinary
from detection.notifications import send_suspicious_detection_email


User = get_user_model()


def _upload_frame_url(frame, camera, *, prefix):
    if frame is None:
        return None

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S_%f")
    public_id = f"{prefix}_camera_{camera.pk}_{camera.user_id}_{timestamp}"
    return upload_frame_to_cloudinary(frame, public_id=public_id)


class DetectionConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time frame prediction"""

    async def connect(self):
        """Authenticate and accept WebSocket connection"""
        # Get token from URL query params
        query_string = self.scope.get("query_string", b"").decode()
        token_str = None

        if "token=" in query_string:
            token_str = query_string.split("token=")[1].split("&")[0]

        if not token_str:
            await self.close()
            return

        try:
            token = AccessToken(token_str)
            user_id = token["user_id"]
            self.user = await database_sync_to_async(User.objects.get)(id=user_id)
            self.prediction_type = "multi"  # Default prediction type
            await self.accept()
            await self.send_json({"status": "connected", "message": "Ready to receive frames"})
        except Exception as e:
            await self.close()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnect"""
        pass

    async def receive(self, text_data):
        """Receive and process frame data"""
        try:
            data = json.loads(text_data)
            image_data = data.get("image")
            camera_id = data.get("camera_id")
            camera_name = data.get("camera_name")
            prediction_type = data.get("type", "multi")  # "multi", "multi15", "multi3d", "14"

            if not image_data:
                await self.send_json({"error": "Image data required"})
                return

            # Decode base64 frame
            try:
                _, imgstr = image_data.split(";base64,")
                img_bytes = base64.b64decode(imgstr)
            except (ValueError, TypeError):
                await self.send_json({"error": "Invalid image format"})
                return

            frame = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                await self.send_json({"error": "Unable to decode image"})
                return

            # Get camera object
            camera = None
            if camera_id:
                camera = await database_sync_to_async(Camera.objects.filter)(user=self.user, id=camera_id)
                camera = camera.first()
            elif camera_name:
                camera = await database_sync_to_async(Camera.objects.filter)(user=self.user, name=camera_name)
                camera = camera.first()

            if not camera:
                await self.send_json({"error": "Camera not found or unauthorized"})
                return

            prediction_key = str(camera.id)
            self.prediction_type = prediction_type

            # Run prediction
            label, confidence = await self._predict(frame, prediction_key, prediction_type)

            if label is None:
                await self.send_json({"label": None, "confidence": None})
                return

            # Build alert if suspicious
            if label == "Suspicious":
                frame_url = await database_sync_to_async(_upload_frame_url)(
                    frame,
                    camera,
                    prefix="websocket_detect",
                )
                alert = await database_sync_to_async(Alert.objects.create)(
                    user=self.user,
                    camera=camera,
                    alert_type="suspicious",
                    confidence=confidence,
                    frame_url=frame_url,
                )
                await database_sync_to_async(send_suspicious_detection_email)(alert)

            response = {"label": label, "confidence": round(confidence, 2)}
            if label == "Suspicious":
                response["frame_url"] = frame_url
            await self.send_json(response)

        except json.JSONDecodeError:
            await self.send_json({"error": "Invalid JSON"})
        except Exception as e:
            await self.send_json({"error": str(e)})

    async def _predict(self, frame, camera_id, prediction_type):
        """Run prediction based on type"""
        try:
            if prediction_type == "14":
                label, confidence = await database_sync_to_async(predict_frame14)(frame, camera_id)
            elif prediction_type == "multi15":
                label, confidence = await database_sync_to_async(predict_frame_multi15)(frame, camera_id)
            elif prediction_type == "multi3d":
                label, confidence = await database_sync_to_async(predict_frame_multi3d)(frame, camera_id)
            else:  # multi (default)
                label, confidence = await database_sync_to_async(predict_frame_multi)(frame, camera_id)

            return label, confidence
        except Exception as e:
            print(f"Prediction error: {e}")
            return None, None

    async def send_json(self, data):
        """Send JSON response to client"""
        await self.send(text_data=json.dumps(data))
