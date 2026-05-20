import base64
import logging
import os
import signal
import tempfile
import urllib.request
from contextlib import contextmanager
from threading import Lock

import cv2
import numpy as np
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from detection.models import VideoPrediction

logger = logging.getLogger(__name__)

# Detection timeout in seconds
DETECTION_TIMEOUT = 60

class TimeoutException(Exception):
    """Raised when a detection operation times out."""
    pass

@contextmanager
def timeout_handler(seconds):
    """Context manager for handling detection timeouts."""
    def _timeout(signum, frame):
        raise TimeoutException(f"Detection operation timed out after {seconds} seconds")
    
    # Only use signal-based timeouts on Unix systems
    try:
        old_handler = signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    except (ValueError, RuntimeError, AttributeError):
        # Fallback: just yield without timeout on systems that don't support SIGALRM
        yield

from api.permissions import IsAuthenticatedWithAdminFullAccess, has_full_access
from alert.models import Alert
from cameras.models import Camera
from detection.ml.pridict_gray import (
    get_last_prediction_debug,
    predict_frame14,
    predict_frame_multi,
    predict_frame_multi15,
    run_video_prediction,
)
from detection.ml.predict3dcnn import predict_frame_multi3d
from detection.ml.predict3dcnn import get_last_prediction_debug as get_last_prediction_debug_3d

from .cloudinary_utils import upload_frame_to_cloudinary
from .notifications import send_suspicious_detection_email
from .serializers import VideoPredictionSerializer, VideoUploadSerializer
from .suspicion_state import should_send_suspicious_email

camera_locks = {}


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
    if has_full_access(user):
        queryset = Camera.objects.all()
    else:
        queryset = Camera.objects.filter(user=user)

    if camera_id is not None:
        return queryset.filter(pk=camera_id).first()

    if camera_name is not None:
        normalized_name = str(camera_name).strip()
        if not normalized_name:
            return None
        return queryset.filter(name__iexact=normalized_name).first()

    return None


def _get_prediction_key(camera):
    return str(camera.pk)


def _build_camera_not_found_response(user, *, camera_id=None, camera_name=None):
    available_cameras = Camera.objects.filter(user=user).values("id", "name")
    return Response(
        {
            "error": "Camera not found or unauthorized",
            "requested_camera_id": camera_id,
            "requested_camera_name": camera_name,
            "available_cameras": list(available_cameras),
        },
        status=403,
    )


def _upload_frame_url(frame, camera, *, prefix):
    if frame is None:
        return None

    timestamp = timezone.now().strftime("%Y%m%d_%H%M%S_%f")
    public_id = f"{prefix}_camera_{camera.pk}_{camera.user_id}_{timestamp}"
    return upload_frame_to_cloudinary(frame, public_id=public_id)


def _get_video_url(video_obj):
    if not video_obj or not video_obj.video:
        return None

    try:
        return video_obj.video.url
    except Exception:
        return None


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

    file_name = getattr(video_field, "name", "") or ""
    suffix = os.path.splitext(file_name)[1] or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        if hasattr(video_field, "open") and hasattr(video_field, "read"):
            video_field.open("rb")
            try:
                while True:
                    chunk = video_field.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)
            finally:
                try:
                    video_field.close()
                except Exception:
                    pass
        else:
            remote_url = getattr(video_field, "url", None)
            if not remote_url:
                raise ValidationError({"error": "Video file could not be accessed"})

            with urllib.request.urlopen(remote_url) as response:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)
        temp_path = temp_file.name

    return temp_path, temp_path


def _build_alert(user, camera, confidence, frame_url=None):
    return Alert.objects.create(
        user=user,
        camera=camera,
        alert_type="suspicious",
        confidence=confidence,
        frame_url=frame_url,
    )


def _prediction_response(label, confidence, frame_url, debug_source):
    payload = {
        "label": label,
        "confidence": round(confidence, 2) if confidence is not None else None,
        "frame_url": frame_url,
        "suspicious_score": None,
        "threshold": None,
    }
    debug_info = get_last_prediction_debug(debug_source)
    if debug_info:
        payload["suspicious_score"] = round(debug_info.get("suspicious_score", 0.0), 4)
        payload["threshold"] = round(debug_info.get("threshold", 0.0), 4)
    return payload


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
            return Response(_prediction_response(None, None, None, f"camera:{prediction_key}"))

        suspicious = label == "Suspicious"
        should_notify = should_send_suspicious_email(camera.pk, suspicious)

        frame_url = None
        if suspicious:
            frame_url = _upload_frame_url(frame, camera, prefix="detect14")
            alert = _build_alert(request.user, camera, confidence, frame_url=frame_url)
            if should_notify:
                send_suspicious_detection_email(alert)

        return Response(_prediction_response(label, confidence, frame_url, f"camera:{prediction_key}"))


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
            return Response(_prediction_response(None, None, None, f"camera:{prediction_key}"))

        suspicious = label == "Suspicious"
        should_notify = should_send_suspicious_email(camera.pk, suspicious)

        frame_url = None
        if suspicious:
            frame_url = _upload_frame_url(frame, camera, prefix="detect_update")
            alert = _build_alert(request.user, camera, confidence, frame_url=frame_url)
            if should_notify:
                send_suspicious_detection_email(alert)

        return Response(_prediction_response(label, confidence, frame_url, f"camera:{prediction_key}"))


class DetectAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")
        camera_id = request.data.get("camera_id")

        if not image_data or (not camera_name and not camera_id):
            return Response({"error": "image and camera_name or camera_id required"}, status=400)

        camera = _get_camera_for_user(
            request.user,
            camera_id=camera_id,
            camera_name=camera_name,
        )
        if camera is None:
            return _build_camera_not_found_response(
                request.user,
                camera_id=camera_id,
                camera_name=camera_name,
            )

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
            return Response(_prediction_response(None, None, None, f"camera:{prediction_key}"))

        suspicious = label == "Suspicious"
        should_notify = should_send_suspicious_email(camera.pk, suspicious)

        frame_url = None
        if suspicious:
            frame_url = _upload_frame_url(frame, camera, prefix="detect")
            alert = _build_alert(request.user, camera, confidence, frame_url=frame_url)
            if should_notify:
                send_suspicious_detection_email(alert)

        return Response(_prediction_response(label, confidence, frame_url, f"camera:{prediction_key}"))


class DetectAPIViewSikp(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")
        camera_id = request.data.get("camera_id")

        if not image_data or (not camera_name and not camera_id):
            return Response({"error": "Image and camera_name or camera_id required"}, status=400)

        camera = _get_camera_for_user(
            request.user,
            camera_id=camera_id,
            camera_name=camera_name,
        )
        if camera is None:
            return _build_camera_not_found_response(
                request.user,
                camera_id=camera_id,
                camera_name=camera_name,
            )

        prediction_key = _get_prediction_key(camera)

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        label, confidence = predict_frame_multi(frame, prediction_key)

        if label is None:
            payload = _prediction_response(None, None, None, f"camera:{prediction_key}")
            payload["sequence_ready"] = False
            return Response(payload)

        suspicious = label == "Suspicious"
        should_notify = should_send_suspicious_email(camera.pk, suspicious)

        frame_url = None
        if suspicious:
            frame_url = _upload_frame_url(frame, camera, prefix="detect_skip")
            alert = _build_alert(request.user, camera, confidence, frame_url=frame_url)
            if should_notify:
                send_suspicious_detection_email(alert)

        payload = _prediction_response(
            label,
            confidence,
            frame_url,
            f"camera:{prediction_key}",
        )
        payload["sequence_ready"] = True
        return Response(payload)


class Detect3DCNNAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        image_data = request.data.get("image")
        camera_name = request.data.get("camera_name")
        camera_id = request.data.get("camera_id")

        if not image_data or (not camera_name and not camera_id):
            return Response({"error": "Image and camera_name or camera_id required"}, status=400)

        camera = _get_camera_for_user(
            request.user,
            camera_id=camera_id,
            camera_name=camera_name,
        )
        if camera is None:
            return _build_camera_not_found_response(
                request.user,
                camera_id=camera_id,
                camera_name=camera_name,
            )

        prediction_key = _get_prediction_key(camera)

        try:
            frame = _decode_base64_frame(image_data)
        except ValidationError as exc:
            return Response(exc.detail, status=400)

        try:
            with timeout_handler(DETECTION_TIMEOUT):
                label, confidence = predict_frame_multi3d(frame, prediction_key)
        except TimeoutException as e:
            logger.error("3D CNN detection timeout for camera %s: %s", camera_id, str(e))
            return Response(
                {"error": "Detection operation timed out", "label": None, "confidence": None},
                status=504,
            )
        except Exception as e:
            logger.exception("3D CNN detection error for camera %s", camera_id)
            return Response(
                {"error": "Detection operation failed", "label": None, "confidence": None},
                status=500,
            )

        if label is None:
            return Response(
                {
                    "label": None,
                    "confidence": None,
                    "frame_url": None,
                    "sequence_ready": False,
                }
            )

        suspicious = label == "Suspicious"
        should_notify = should_send_suspicious_email(camera.pk, suspicious)

        frame_url = None
        if suspicious:
            try:
                frame_url = _upload_frame_url(frame, camera, prefix="detect_3dcnn")
                alert = _build_alert(request.user, camera, confidence, frame_url=frame_url)
                if should_notify:
                    send_suspicious_detection_email(alert)
            except Exception as e:
                logger.exception("Failed to upload frame or send alert for camera %s", camera_id)
                # Don't fail the request if upload fails - alert is already created

        return Response(
            {
                "label": label,
                "confidence": round(confidence, 2),
                "frame_url": frame_url,
                "sequence_ready": True,
                "suspicious_score": round(
                    get_last_prediction_debug_3d(f"camera:{prediction_key}:3d").get("suspicious_score", 0.0),
                    4,
                ),
                "threshold": round(
                    get_last_prediction_debug_3d(f"camera:{prediction_key}:3d").get("threshold", 0.0),
                    4,
                ),
            }
        )


class VideoPredictionViewSet(viewsets.ModelViewSet):
    serializer_class = VideoPredictionSerializer
    permission_classes = [IsAuthenticatedWithAdminFullAccess]

    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return VideoPrediction.objects.none()
        if has_full_access(self.request.user):
            return VideoPrediction.objects.all().select_related("camera", "user")
        return VideoPrediction.objects.filter(user=self.request.user).select_related("camera")

    def perform_create(self, serializer):
        camera = serializer.validated_data.get("camera")
        if (
            camera is not None
            and camera.user_id != self.request.user.id
            and not has_full_access(self.request.user)
        ):
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
                video_url = _get_video_url(video_obj)
            except Exception:
                video_url = None

            final, suspicious, normal, suspicious_frame = run_video_prediction(
                local_video_path,
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
                    "suspicious_score": round(get_last_prediction_debug("video").get("suspicious_score", 0.0), 4),
                    "threshold": round(get_last_prediction_debug("video").get("threshold", 0.0), 4),
                }
            )
        except Exception as exc:
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
                    pass
class VideoPredictionAPIView(APIView):
    def post(self, request):
        serializer = VideoUploadSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )

        video_file = serializer.validated_data["video"]

        suffix = os.path.splitext(getattr(video_file, "name", "") or "")[1] or ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as destination:
            temp_path = destination.name
            for chunk in video_file.chunks():
                destination.write(chunk)

        try:
            label, suspicious, normal, _ = run_video_prediction(
                temp_path
            )

            response_data = {
                "prediction": label,
                "suspicious_count": suspicious,
                "normal_count": normal,
                "suspicious_score": round(get_last_prediction_debug("video").get("suspicious_score", 0.0), 4),
                "threshold": round(get_last_prediction_debug("video").get("threshold", 0.0), 4),
            }

            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
