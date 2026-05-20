import logging
import os
import time
from threading import Lock

import cv2
import numpy as np
import onnxruntime as ort
from cameras.models import Camera
from django.core.files.base import ContentFile
from django.utils import timezone

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(BASE_DIR, "ml", "best_3dcnn_model.onnx")

SEQ_LEN = 16
IMG_SIZE = 160
SKIP_RATE = 1
SUSPICIOUS_THRESHOLD = float(os.getenv("SUSPICIOUS_THRESHOLD_3D", "0.40"))
CAMERA_STATE_TTL_SECONDS = int(os.getenv("CAMERA_STATE_TTL_SECONDS", "900"))
MAX_CAMERA_STATES = int(os.getenv("MAX_CAMERA_STATES", "128"))
ONNX_INTRA_OP_THREADS = int(os.getenv("ONNX_INTRA_OP_THREADS", "1"))

session_options = ort.SessionOptions()
session_options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
session_options.inter_op_num_threads = 1
session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

session = ort.InferenceSession(
    model_path,
    sess_options=session_options,
    providers=["CPUExecutionProvider"],
)
input_name = session.get_inputs()[0].name

camera_buffers = {}
camera_locks = {}
camera_frame_counts = {}
camera_timestamps = {}
camera_skip_counters = {}
camera_skip_rates = {}
camera_last_seen = {}
last_prediction_debug = {}


def is_model_loaded():
    return session is not None


def warmup_model():
    dummy_input = np.zeros((1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 3), dtype=np.float32)
    session.run(None, {input_name: dummy_input})
    logger.info("3D CNN ONNX model warmup complete")
    return True


def get_last_prediction_debug(source):
    return last_prediction_debug.get(source, {})


def _save_camera_snapshot(camera, frame, *, prefix="suspicious"):
    if camera is None or frame is None or frame.size == 0:
        return

    _, buffer_jpg = cv2.imencode(".jpg", frame)
    filename = f"{prefix}_{timezone.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    camera.snapshot.save(filename, ContentFile(buffer_jpg.tobytes()), save=False)
    camera.last_seen = timezone.now()
    camera.status = "online"
    camera.save(update_fields=["snapshot", "last_seen", "status"])


def _cleanup_camera_state(now=None, *, force=False):
    now = now or time.time()

    stale_camera_ids = [
        camera_id
        for camera_id, last_seen in camera_last_seen.items()
        if now - last_seen > CAMERA_STATE_TTL_SECONDS
    ]

    if force and not stale_camera_ids and len(camera_last_seen) > MAX_CAMERA_STATES:
        overflow = len(camera_last_seen) - MAX_CAMERA_STATES
        stale_camera_ids = sorted(camera_last_seen, key=camera_last_seen.get)[:overflow]

    for camera_id in stale_camera_ids:
        camera_buffers.pop(camera_id, None)
        camera_locks.pop(camera_id, None)
        camera_frame_counts.pop(camera_id, None)
        camera_timestamps.pop(camera_id, None)
        camera_skip_counters.pop(camera_id, None)
        camera_skip_rates.pop(camera_id, None)
        camera_last_seen.pop(camera_id, None)


def _to_probability(raw_pred):
    pred_value = float(np.array(raw_pred, dtype=np.float32).squeeze())
    if pred_value < 0.0 or pred_value > 1.0:
        pred_value = 1.0 / (1.0 + np.exp(-pred_value))
    return float(pred_value)


def set_camera_skip_rate_3d(camera_id, skip_rate):
    camera_skip_rates[camera_id] = skip_rate
    logger.info("[%s] 3D skip rate set to %s", camera_id, skip_rate)


def predict_frame_multi3d(frame, camera_id, skip_rate=None):
    if frame is None or frame.size == 0:
        return None, None

    if skip_rate is None:
        skip_rate = camera_skip_rates.get(camera_id, SKIP_RATE)

    lock = camera_locks.setdefault(camera_id, Lock())
    with lock:
        now = time.time()
        camera_last_seen[camera_id] = now
        _cleanup_camera_state(now, force=True)

        original_frame = frame.copy()

        if camera_id not in camera_buffers:
            camera_buffers[camera_id] = []
            camera_frame_counts[camera_id] = 0
            camera_timestamps[camera_id] = []
            camera_skip_counters[camera_id] = 0

        buffer = camera_buffers[camera_id]
        timestamps = camera_timestamps[camera_id]
        skip_counter = camera_skip_counters[camera_id]

        skip_counter = (skip_counter + 1) % skip_rate
        camera_skip_counters[camera_id] = skip_counter

        if skip_counter != 0:
            return None, None

        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(
                frame_rgb,
                (IMG_SIZE, IMG_SIZE),
                interpolation=cv2.INTER_LINEAR,
            )
            frame_norm = frame_resized.astype(np.float32) / 255.0
        except Exception:
            logger.exception("3D CNN preprocessing error for camera %s", camera_id)
            return None, None

        buffer.append(frame_norm)
        timestamps.append(camera_frame_counts[camera_id])
        camera_frame_counts[camera_id] += 1

        if len(buffer) > SEQ_LEN:
            buffer = buffer[-SEQ_LEN:]
            timestamps = timestamps[-SEQ_LEN:]
            camera_buffers[camera_id] = buffer
            camera_timestamps[camera_id] = timestamps

        if len(buffer) < SEQ_LEN:
            return None, None

        try:
            input_array = np.expand_dims(np.stack(buffer, axis=0), axis=0).astype(np.float32)
            prediction = session.run(None, {input_name: input_array})[0]
            suspicious_score = _to_probability(prediction)
        except Exception:
            logger.exception("3D CNN ONNX prediction error for camera %s", camera_id)
            return None, None

        label = "Suspicious" if suspicious_score >= SUSPICIOUS_THRESHOLD else "Normal"
        confidence = suspicious_score if label == "Suspicious" else 1.0 - suspicious_score
        source = f"camera:{camera_id}:3d"
        last_prediction_debug[source] = {
            "suspicious_score": float(suspicious_score),
            "threshold": float(SUSPICIOUS_THRESHOLD),
            "label": label,
            "confidence": float(confidence),
        }

        if label == "Suspicious":
            try:
                camera = Camera.objects.get(id=camera_id)
                _save_camera_snapshot(camera, original_frame)
            except Camera.DoesNotExist:
                logger.warning("Camera %s not found during 3D snapshot save", camera_id)
            except Exception:
                logger.exception("3D snapshot save error for camera %s", camera_id)

        return label, float(confidence)
