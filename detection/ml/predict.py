
# only label and confidence

import os
import numpy as np
import cv2
from threading import Lock
import tensorflow as tf
from tensorflow.keras.models import load_model  # type: ignore
from django.conf import settings
from cameras.models import Camera

# Enable mixed precision for faster computation
try:
    policy = tf.keras.mixed_precision.Policy('mixed_float16')
    tf.keras.mixed_precision.set_global_policy(policy)
except:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
model_path = os.path.join(BASE_DIR, "ml", "best_cnn_lstm_model.h5")

# Load model ONCE
model = load_model(model_path)

# Compile model for faster inference
model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

# Create a TF function wrapper for faster prediction
@tf.function(reduce_retracing=True)
def _fast_predict(input_array):
    """TensorFlow compiled function for fast prediction"""
    return model(input_array, training=False)

SEQ_LEN = 16
IMG_SIZE = 160

# Frame skipping configuration (configurable per camera)
# SKIP_RATE = 1 means process every frame (no skipping, slower but more accurate)
# SKIP_RATE = 2 means process every 2nd frame (faster, still good accuracy)
# SKIP_RATE = 3 means process every 3rd frame (fastest, good for high FPS cameras)
SKIP_RATE = 1  # Can be overridden per camera

# Global camera buffers and locks
camera_buffers = {}
camera_locks = {}
camera_frame_counts = {}   # Track frame count per camera for debugging
camera_timestamps = {}     # Track timestamps for frame sequencing
camera_skip_counters = {}  # Track skip count for frame skipping
camera_skip_rates = {}     # Configurable skip rate per camera (default: SKIP_RATE)


def set_camera_skip_rate(camera_id, skip_rate):
    """
    Set frame skip rate for a specific camera.
    skip_rate=1: process every frame (no skipping)
    skip_rate=2: process every 2nd frame (50% faster)
    skip_rate=3: process every 3rd frame (66% faster)
    """
    camera_skip_rates[camera_id] = skip_rate
    print(f"[{camera_id}] Skip rate set to {skip_rate}")


def predict_frame14(frame, camera_id="default", skip_rate=None):
    """
    Optimized prediction with intelligent frame skipping.
    
    Args:
        frame: Input frame
        camera_id: Camera identifier
        skip_rate: Override skip rate for this call (1=no skip, 2=every 2nd, etc.)
    
    Returns:
        (label, confidence) or (None, None) if still collecting frames
    """
    if frame is None or frame.size == 0:
        return None, None

    # Determine skip rate for this camera
    if skip_rate is None:
        skip_rate = camera_skip_rates.get(camera_id, SKIP_RATE)

    # Get camera lock
    lock = camera_locks.setdefault(camera_id, Lock())
    with lock:
        # Initialize camera state if needed
        if camera_id not in camera_buffers:
            camera_buffers[camera_id] = []
            camera_frame_counts[camera_id] = 0
            camera_timestamps[camera_id] = []
            camera_skip_counters[camera_id] = 0

        skip_counter = camera_skip_counters[camera_id]
        buffer = camera_buffers[camera_id]
        timestamps = camera_timestamps[camera_id]

        # Increment skip counter
        skip_counter = (skip_counter + 1) % skip_rate
        camera_skip_counters[camera_id] = skip_counter

        # Skip this frame if skip_counter != 0
        if skip_counter != 0:
            return None, None  # Skip this frame

        # Preprocess frame (only if we're not skipping it)
        try:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame = cv2.resize(frame, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
            frame = frame.astype("float32") / 255.0
        except Exception as e:
            print(f"Frame preprocessing error: {e}")
            return None, None

        # Add frame to buffer (only frames that aren't skipped)
        buffer.append(frame)
        timestamps.append(camera_frame_counts[camera_id])
        camera_frame_counts[camera_id] += 1

        # Keep only last SEQ_LEN frames - proper sliding window
        if len(buffer) > SEQ_LEN:
            buffer = buffer[-SEQ_LEN:]
            timestamps = timestamps[-SEQ_LEN:]
            camera_buffers[camera_id] = buffer
            camera_timestamps[camera_id] = timestamps

        # Not enough frames yet - return None to signal buffering
        if len(buffer) < SEQ_LEN:
            return None, None

        # Stack frames for prediction
        try:
            buffer_array = np.stack(buffer, axis=0)  # (SEQ_LEN, IMG_SIZE, IMG_SIZE, 3)
            input_array = np.expand_dims(buffer_array, axis=0)  # (1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 3)
            
            # Convert to tensor once
            input_tensor = tf.convert_to_tensor(input_array, dtype=tf.float32)
            
            # Use fast prediction
            prediction = _fast_predict(input_tensor).numpy()[0][0]
            
        except Exception as e:
            print(f"Model prediction error: {e}")
            return None, None

        label = "Suspicious" if prediction > 0.5 else "Normal"
        confidence = float(prediction) if prediction > 0.5 else float(1 - prediction)

        return label, confidence
    


from django.core.files.base import ContentFile
from django.utils import timezone


def _save_camera_snapshot(camera, frame, *, prefix="suspicious"):
    if camera is None or frame is None or frame.size == 0:
        return

    _, buffer_jpg = cv2.imencode(".jpg", frame)
    filename = f"{prefix}_{timezone.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
    camera.snapshot.save(filename, ContentFile(buffer_jpg.tobytes()), save=False)
    camera.last_seen = timezone.now()
    camera.status = "online"
    camera.save(update_fields=["snapshot", "last_seen", "status"])

def predict_frame_multi(frame, camera_id, skip_rate=None):
    """
    Optimized prediction with intelligent frame skipping and snapshot saving.
    
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
        
        # Keep only last SEQ_LEN frames (sliding window)
        if len(buffer) > SEQ_LEN:
            buffer = buffer[-SEQ_LEN:]
            timestamps = timestamps[-SEQ_LEN:]
            camera_buffers[camera_id] = buffer
            camera_timestamps[camera_id] = timestamps

        # Wait until buffer full
        if len(buffer) < SEQ_LEN:
            return None, None

        # Prepare input for model
        try:
            input_array = np.expand_dims(np.stack(buffer, axis=0), axis=0)  # (1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 3)
            
            # Convert to tensor once
            input_tensor = tf.convert_to_tensor(input_array, dtype=tf.float32)
            
            # Use fast prediction
            prediction = _fast_predict(input_tensor).numpy()[0][0]
            
        except Exception as e:
            print(f"Model prediction error: {e}")
            return None, None

        label = "Suspicious" if prediction > 0.5 else "Normal"
        confidence = float(prediction) if prediction > 0.5 else float(1 - prediction)

        # Update snapshot ONLY if suspicious
        if label == "Suspicious":
            try:
                camera = Camera.objects.get(id=camera_id)
                _save_camera_snapshot(camera, frame)
            except Camera.DoesNotExist:
                print(f"Camera {camera_id} not found")
            except Exception as e:
                print(f"Snapshot save error: {e}")

        return label, confidence
    

def predict_frame_multi15(frame, camera_name, skip_rate=None):
    """
    Optimized prediction with intelligent frame skipping.
    
    Args:
        frame: Input frame
        camera_name: Camera name identifier
        skip_rate: Override skip rate for this call (1=no skip, 2=every 2nd, etc.)
    """
    if frame is None or frame.size == 0:
        return None, None

    # Determine skip rate for this camera
    if skip_rate is None:
        skip_rate = camera_skip_rates.get(camera_name, SKIP_RATE)

    lock = camera_locks.setdefault(camera_name, Lock())

    with lock:
        # Initialize camera state if needed
        if camera_name not in camera_buffers:
            camera_buffers[camera_name] = []
            camera_frame_counts[camera_name] = 0
            camera_timestamps[camera_name] = []
            camera_skip_counters[camera_name] = 0

        buffer = camera_buffers[camera_name]
        timestamps = camera_timestamps[camera_name]
        skip_counter = camera_skip_counters[camera_name]

        # Increment skip counter
        skip_counter = (skip_counter + 1) % skip_rate
        camera_skip_counters[camera_name] = skip_counter

        # Skip this frame if skip_counter != 0
        if skip_counter != 0:
            return None, None  # Skip this frame

        # Preprocess (only if we're not skipping)
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(frame_rgb, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
            normalized = resized.astype("float32") / 255.0
        except Exception as e:
            print(f"[PREPROCESS ERROR] {e}")
            return None, None

        # Add frame to buffer - preserve order, no skipping in buffer
        buffer.append(normalized)
        timestamps.append(camera_frame_counts[camera_name])
        camera_frame_counts[camera_name] += 1

        # Keep last SEQ_LEN frames (sliding window)
        if len(buffer) > SEQ_LEN:
            del buffer[:-SEQ_LEN]
            timestamps = timestamps[-SEQ_LEN:]

        camera_buffers[camera_name] = buffer
        camera_timestamps[camera_name] = timestamps

        # not enough frames yet
        if len(buffer) < SEQ_LEN:
            return None, None

        # Prediction (optimized with @tf.function)
        try:
            input_array = np.expand_dims(np.array(buffer), axis=0)

            if input_array.shape != (1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 3):
                print("[SHAPE ERROR]", input_array.shape)
                return None, None

            # Convert to tensor and use fast predict
            input_tensor = tf.convert_to_tensor(input_array, dtype=tf.float32)
            pred = _fast_predict(input_tensor).numpy()

        except Exception as e:
            print("[PRED ERROR]", e)
            return None, None

        # SAFE PARSING
        pred = np.array(pred).squeeze()

        # sigmoid case
        if pred.ndim == 0:
            pred_value = float(pred)
        else:
            # softmax case → take class index + confidence
            pred_value = float(np.max(pred))

        # LABEL
        label = "Suspicious" if pred_value > 0.5 else "Normal"
        confidence = max(pred_value, 1 - pred_value)

        print(f"[{camera_name}] {label} | {confidence:.2f}")

        # snapshot
        if label == "Suspicious":
            try:
                cam = Camera.objects.filter(id=camera_name).first()
                if cam is None:
                    cam = Camera.objects.filter(name=camera_name).first()

                if cam:
                    filename = f"{camera_name}_{int(cv2.getTickCount())}.jpg"
                    path = os.path.join(settings.MEDIA_ROOT, "snapshots", filename)

                    cv2.imwrite(path, frame)

                    cam.snapshot = f"snapshots/{filename}"
                    cam.save(update_fields=["snapshot"])

            except Exception as e:
                print("Snapshot error:", e)

        return label, confidence
    


#vide predict

import cv2
import numpy as np

SEQ_LEN = 16
IMG_SIZE = 160

def run_video_prediction(video_path, model, *, camera=None, stop_on_suspicious=True):
    """Run video prediction and optionally stop as soon as suspicious activity is found."""
    cap = cv2.VideoCapture(video_path)

    frames = []
    suspicious = 0
    normal = 0
    snapshot_saved = False
    first_suspicious_frame = None

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        original_frame = frame.copy()
        frame = cv2.resize(frame, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_LINEAR)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame = frame.astype("float32") / 255.0

        frames.append(frame)

        if len(frames) == SEQ_LEN:
            try:
                input_array = np.expand_dims(np.array(frames), axis=0)
                
                # Convert to tensor and use fast predict
                input_tensor = tf.convert_to_tensor(input_array, dtype=tf.float32)
                pred = _fast_predict(input_tensor).numpy()
                
                pred = np.array(pred).squeeze()

                pred_value = float(np.max(pred))

                label = "Suspicious" if pred_value > 0.5 else "Normal"
            except Exception as e:
                print(f"Video prediction error: {e}")
                frames.pop(0)
                continue

            if label == "Suspicious":
                suspicious += 1
                if first_suspicious_frame is None:
                    first_suspicious_frame = original_frame
                if camera is not None and not snapshot_saved:
                    try:
                        _save_camera_snapshot(camera, original_frame, prefix="video_suspicious")
                        snapshot_saved = True
                    except Exception as e:
                        print(f"Video snapshot save error: {e}")

                if stop_on_suspicious:
                    cap.release()
                    return "Suspicious", suspicious, normal, first_suspicious_frame
            else:
                normal += 1

            frames.pop(0)

    cap.release()

    final = "Suspicious" if suspicious > normal else "Normal"

    return final, suspicious, normal, first_suspicious_frame
