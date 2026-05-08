
# only label and confidence

import os
import numpy as np
import cv2
from threading import Lock
import tensorflow as tf
from tensorflow.keras.models import load_model  # type: ignore

# Enable mixed precision for faster computation
try:
    policy = tf.keras.mixed_precision.Policy('mixed_float16')
    tf.keras.mixed_precision.set_global_policy(policy)
except:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(BASE_DIR, "ml", "best_3dcnn_model.h5")

model = None
model_lock = Lock()


def _get_model():
    """Load the TensorFlow model lazily so web startup does not stall port binding."""
    global model
    if model is None:
        with model_lock:
            if model is None:
                model = load_model(model_path, compile=False)
    return model


def is_model_loaded():
    return model is not None


def warmup_model():
    _get_model()
    return True

# Global camera buffers and locks
camera_buffers = {}
camera_locks = {}
camera_frame_counts = {}   # Track frame count per camera
camera_timestamps = {}     # Track timestamps for frame sequencing
camera_skip_counters = {}  # Track skip count for frame skipping
camera_skip_rates = {}     # Configurable skip rate per camera



import numpy as np
# import cv2
from django.core.files.base import ContentFile
from django.utils import timezone
from cameras.models import Camera

SEQ_LEN = 16
IMG_SIZE = 160

# Frame skipping configuration
SKIP_RATE = 1  # Can be overridden per camera


def _save_camera_snapshot(camera, frame, *, prefix="suspicious"):
    if camera is None or frame is None or frame.size == 0:
        return

    _, buffer_jpg = cv2.imencode(".jpg", frame)
    filename = f"{prefix}_{timezone.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    camera.snapshot.save(filename, ContentFile(buffer_jpg.tobytes()), save=False)
    camera.last_seen = timezone.now()
    camera.status = "online"
    camera.save(update_fields=["snapshot", "last_seen", "status"])

def set_camera_skip_rate_3d(camera_id, skip_rate):
    """
    Set frame skip rate for a specific camera.
    skip_rate=1: process every frame (no skipping)
    skip_rate=2: process every 2nd frame (50% faster)
    skip_rate=3: process every 3rd frame (66% faster)
    """
    camera_skip_rates[camera_id] = skip_rate
    print(f"[{camera_id}] Skip rate set to {skip_rate}")


def predict_frame_multi3d(frame, camera_id, skip_rate=None):
    """
    Optimized 3D CNN prediction with intelligent frame skipping.
    
    Args:
        frame: Input frame
        camera_id: Camera identifier
        skip_rate: Override skip rate for this call (1=no skip, 2=every 2nd, etc.)
    """
    if frame is None or frame.size == 0:
        return None, None

    # Determine skip rate for this camera
    if skip_rate is None:
        skip_rate = camera_skip_rates.get(camera_id, SKIP_RATE)

    # Thread-safe buffer
    lock = camera_locks.setdefault(camera_id, Lock())
    with lock:
        original_frame = frame.copy()

        # Initialize camera state if needed
        if camera_id not in camera_buffers:
            camera_buffers[camera_id] = []
            camera_frame_counts[camera_id] = 0
            camera_timestamps[camera_id] = []
            camera_skip_counters[camera_id] = 0

        buffer = camera_buffers[camera_id]
        timestamps = camera_timestamps[camera_id]
        skip_counter = camera_skip_counters[camera_id]

        # Increment skip counter
        skip_counter = (skip_counter + 1) % skip_rate
        camera_skip_counters[camera_id] = skip_counter

        # Skip this frame if skip_counter != 0
        if skip_counter != 0:
            return None, None  # Skip this frame

        # Preprocess (only if we're not skipping)
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_resized = cv2.resize(frame_rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
            frame_norm = frame_resized.astype("float32") / 255.0
        except Exception as e:
            print(f"Preprocessing error: {e}")
            return None, None

        # Add frame to buffer - preserve order, no skipping in buffer
        buffer.append(frame_norm)
        timestamps.append(camera_frame_counts[camera_id])
        camera_frame_counts[camera_id] += 1
        
        # Keep only last SEQ_LEN frames - proper sliding window
        if len(buffer) > SEQ_LEN:
            buffer = buffer[-SEQ_LEN:]
            timestamps = timestamps[-SEQ_LEN:]
            camera_buffers[camera_id] = buffer
            camera_timestamps[camera_id] = timestamps

        if len(buffer) < SEQ_LEN:
            return None, None  # Wait until buffer full

        # Prepare input for model
        try:
            input_array = np.expand_dims(np.stack(buffer, axis=0), axis=0)  # (1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 3)
            
            # Convert to tensor once
            input_tensor = tf.convert_to_tensor(input_array, dtype=tf.float32)
            
            loaded_model = _get_model()
            prediction = loaded_model(input_tensor, training=False).numpy()[0][0]
            
        except Exception as e:
            print(f"Model prediction error: {e}")
            return None, None

        label = "Suspicious" if prediction > 0.5 else "Normal"
        confidence = float(prediction) if prediction > 0.5 else float(1 - prediction)

        # Update snapshot ONLY if suspicious
        if label == "Suspicious":
            try:
                camera = Camera.objects.get(id=camera_id)
                _save_camera_snapshot(camera, original_frame)
            except Camera.DoesNotExist:
                print(f"Camera {camera_id} not found")
            except Exception as e:
                print(f"Snapshot save error: {e}")

        return label, confidence
