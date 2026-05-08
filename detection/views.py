import base64
import logging
import os
import tempfile
from threading import Lock

import cv2
import numpy as np
from django.utils import timezone
from rest_framework import permissions, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from alert.models import Alert
from cameras.models import Camera
from detection.ml.predict import (
    _get_model,
    predict_frame14,
    predict_frame_multi,
    predict_frame_multi15,
    run_video_prediction,
)
from detection.ml.predict3dcnn import predict_frame_multi3d

from .cloudinary_utils import upload_frame_to_cloudinary, upload_video_to_cloudinary
from .models import VideoPrediction
from .notifications import send_suspicious_detection_email
from .serializers import VideoPredictionSerializer


logger = logging.getLogger(__name__)
camera_locks = {}
frame_counters = {}


def _decode_base64_frame(image_data):
    try:
        _, imgstr = image_data.split(";base64,")
        img_bytes = base64.b64decode(imgstr)
    except (ValueError, TypeError):
        raise ValidationError({"error": "Invalid image format"})

    frame = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValidationError({"error": "Unable to decode image"})
    return frame


def _get_camera_for_user(user, *, camera_id=None, camera_name=None):
    queryset = Camera.objects.filter(user=user)

    if camera_id is not None:
        return queryset.filter(pk=camera_id).first()

    if camera_name is not None:
        return queryset.filter(name=camera_name).first()

    return None


def _get_prediction_key(camera):
    return str(camera.pk)


def _upload_frame_url(frame, camera, *, prefix):
    if frame is None:
        return None

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S_%f")
    public_id = f"{prefix}_camera_{camera.pk}_{camera.user_id}_{timestamp}"
    return upload_frame_to_cloudinary(frame, public_id=public_id)


def _upload_video_url(video_obj, local_video_path=None):
    if not video_obj or not video_obj.video:
        return None

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S_%f")
    public_id = f"video_prediction_{video_obj.id}_{video_obj.user_id}_{timestamp}"
    return upload_video_to_cloudinary(local_video_path or video_obj.video.path, public_id=public_id)


def _materialize_video_file(video_field):
    """
    Ensure we have a readable local file path even when the storage backend
    cannot provide a stable on-disk path inside the running container.
    """
    if not video_field:
        raise ValidationError({"error": "Video file is required"})

    temp_path = None

    try:
        candidate_path = video_field.path
    except (AttributeError, NotImplementedError, ValueError):
        candidate_path = None

    if candidate_path and os.path.exists(candidate_path):
        return candidate_path, temp_path

    suffix = os.path.splitext(getattr(video_field, "name", "") or "")[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        for chunk in video_field.chunks():
            temp_file.write(chunk)
        temp_path = temp_file.name

    return temp_path, temp_path


def _build_alert(user, camera, confidence, frame_url=None):
    alert = Alert.objects.create(
        user=user,
        camera=camera,
        alert_type="suspicious",
        confidence=confidence,
        frame_url=frame_url,
    )
    send_suspicious_detection_email(alert)
    return alert


class DetectAPIView14(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_id = request.data.get("camera_id")

        if not image_data or not camera_id:
            return Response({"error": "Image and camera_id are required"}, status=400)

        camera = _get_camera_for_user(request.user, camera_id=camera_id)
        if camera is None:
            return Response({"error": "Camera not found or unauthorized"}, status=403)

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        prediction_key = _get_prediction_key(camera)

        lock = camera_locks.setdefault(prediction_key, Lock())
        with lock:
            label, confidence = predict_frame14(frame, prediction_key)

        if label is None:
            return Response({"label": None, "confidence": None, "frame_url": None})

        frame_url = None
        if label == "Suspicious":
            frame_url = _upload_frame_url(frame, camera, prefix="detect14")
            _build_alert(request.user, camera, confidence, frame_url=frame_url)

        return Response({"label": label, "confidence": round(confidence, 2), "frame_url": frame_url})


class DetectAPIViewUpdate(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_id = request.data.get("camera_id")

        if not image_data or not camera_id:
            return Response({"error": "Image and camera_id are required"}, status=400)

        camera = _get_camera_for_user(request.user, camera_id=camera_id)
        if camera is None:
            return Response({"error": "Camera not found or unauthorized"}, status=403)

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        prediction_key = _get_prediction_key(camera)
        label, confidence = predict_frame_multi(frame, prediction_key)

        if label is None:
            return Response({"label": None, "confidence": None, "frame_url": None})

        frame_url = None
        if label == "Suspicious":
            frame_url = _upload_frame_url(frame, camera, prefix="detect_update")
            _build_alert(request.user, camera, confidence, frame_url=frame_url)

        return Response({"label": label, "confidence": round(confidence, 2), "frame_url": frame_url})


class DetectAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")

        if not image_data or not camera_name:
            return Response({"error": "image and camera_name required"}, status=400)

        camera = _get_camera_for_user(request.user, camera_name=camera_name)
        if camera is None:
            return Response({"error": "Camera not found or unauthorized"}, status=403)

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        prediction_key = _get_prediction_key(camera)
        try:
            label, confidence = predict_frame_multi15(frame, prediction_key)
        except Exception:
            return Response({"error": "Prediction failed"}, status=500)

        if label is None:
            return Response({"label": None, "confidence": None, "frame_url": None})

        frame_url = None
        if label == "Suspicious":
            frame_url = _upload_frame_url(frame, camera, prefix="detect")
            _build_alert(request.user, camera, confidence, frame_url=frame_url)

        return Response({"label": label, "confidence": round(confidence, 2), "frame_url": frame_url})


class DetectAPIViewSikp(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")

        if not image_data or not camera_name:
            return Response({"error": "Image and camera_name required"}, status=400)

        camera = _get_camera_for_user(request.user, camera_name=camera_name)
        if camera is None:
            return Response({"error": "Camera not authorized"}, status=403)

        prediction_key = _get_prediction_key(camera)
        frame_counters[prediction_key] = frame_counters.get(prediction_key, 0) + 1

        if frame_counters[prediction_key] % 3 != 0:
            return Response({"label": None, "confidence": None, "frame_url": None})

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        label, confidence = predict_frame_multi(frame, prediction_key)

        if label is None:
            return Response({"label": None, "confidence": None, "frame_url": None})

        frame_url = None
        if label == "Suspicious":
            frame_url = _upload_frame_url(frame, camera, prefix="detect_skip")
            _build_alert(request.user, camera, confidence, frame_url=frame_url)

        return Response({"label": label, "confidence": round(confidence, 2), "frame_url": frame_url})


class Detect3DCNNAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")

        if not image_data or not camera_name:
            return Response({"error": "Image and camera_name required"}, status=400)

        camera = _get_camera_for_user(request.user, camera_name=camera_name)
        if camera is None:
            return Response({"error": "Camera not authorized"}, status=403)

        prediction_key = _get_prediction_key(camera)
        frame_counters[prediction_key] = frame_counters.get(prediction_key, 0) + 1

        if frame_counters[prediction_key] % 3 != 0:
            return Response({"label": None, "confidence": None, "frame_url": None})

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        label, confidence = predict_frame_multi3d(frame, prediction_key)

        if label is None:
            return Response({"label": None, "confidence": None, "frame_url": None})

        frame_url = None
        if label == "Suspicious":
            frame_url = _upload_frame_url(frame, camera, prefix="detect_3dcnn")
            _build_alert(request.user, camera, confidence, frame_url=frame_url)

        return Response({"label": label, "confidence": round(confidence, 2), "frame_url": frame_url})


class VideoPredictionViewSet(viewsets.ModelViewSet):
    serializer_class = VideoPredictionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return VideoPrediction.objects.filter(user=self.request.user).select_related("camera")

    def perform_create(self, serializer):
        camera = serializer.validated_data.get("camera")
        if camera is not None and camera.user_id != self.request.user.id:
            raise PermissionDenied("You can only create predictions for your own cameras.")
        serializer.save(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        video_obj = serializer.instance
        local_video_path = None
        temp_path = None

        try:
            local_video_path, temp_path = _materialize_video_file(video_obj.video)

            try:
                video_url = _upload_video_url(video_obj, local_video_path=local_video_path)
            except Exception:
                logger.exception("Video upload to Cloudinary failed for prediction %s", video_obj.id)
                video_url = None

            final, suspicious, normal, suspicious_frame = run_video_prediction(
                local_video_path,
                _get_model(),
                camera=video_obj.camera,
            )

            suspicious_frame_url = None
            if final == "Suspicious" and suspicious_frame is not None and video_obj.camera is not None:
                suspicious_frame_url = _upload_frame_url(
                    suspicious_frame,
                    video_obj.camera,
                    prefix="video_prediction",
                )

            video_obj.final_result = final
            video_obj.suspicious_frames = suspicious
            video_obj.normal_frames = normal
            video_obj.video_url = video_url
            video_obj.suspicious_frame_url = suspicious_frame_url
            video_obj.save(
                update_fields=[
                    "final_result",
                    "suspicious_frames",
                    "normal_frames",
                    "video_url",
                    "suspicious_frame_url",
                ]
            )

            frame_url = None
            if final == "Suspicious" and video_obj.camera is not None:
                frame_url = suspicious_frame_url
                _build_alert(request.user, video_obj.camera, 1.0, frame_url=frame_url)

            return Response(
                {
                    "id": video_obj.id,
                    "video_url": video_obj.video_url,
                    "final_result": final,
                    "suspicious_frames": suspicious,
                    "normal_frames": normal,
                    "frame_url": video_obj.suspicious_frame_url,
                    "suspicious_frame_url": video_obj.suspicious_frame_url,
                }
            )
        except Exception as exc:
            logger.exception("Video prediction failed for prediction %s", getattr(video_obj, "id", None))
            return Response(
                {
                    "error": "Video prediction failed",
                    "details": str(exc),
                },
                status=500,
            )
        finally:
            if temp_path and local_video_path and os.path.exists(local_video_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning("Failed to clean up temp video file %s", local_video_path)
