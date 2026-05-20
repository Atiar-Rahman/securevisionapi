import cv2
import numpy as np
import onnxruntime as ort
import logging
import os
import time

from collections import deque
from threading import Lock

# =========================================================
# CONFIG
# =========================================================

SEQ_LEN = 8
IMG_SIZE = 96

# increase threshold to reduce false positives
SUSPICIOUS_THRESHOLD = float(
    os.getenv("SUSPICIOUS_THRESHOLD", "0.40")
)

# voting system
MIN_SUSPICIOUS_VOTES = 3

# debug mode
DEBUG = os.getenv("PREDICTION_DEBUG", "False").strip().lower() == "true"

# state cleanup
CAMERA_STATE_TTL_SECONDS = int(os.getenv("CAMERA_STATE_TTL_SECONDS", "900"))
MAX_CAMERA_STATES = int(os.getenv("MAX_CAMERA_STATES", "256"))
ONNX_INTRA_OP_THREADS = int(os.getenv("ONNX_INTRA_OP_THREADS", "1"))

logger = logging.getLogger(__name__)

# =========================================================
# MODEL PATH
# =========================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

model_path = os.path.join(
    BASE_DIR,
    "ml",
    "best_cnn_lstm_model_gray_version2.onnx"
)

# =========================================================
# LOAD ONNX MODEL
# =========================================================

session_options = ort.SessionOptions()
session_options.intra_op_num_threads = ONNX_INTRA_OP_THREADS
session_options.inter_op_num_threads = 1
session_options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
session_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

session = ort.InferenceSession(
    model_path,
    sess_options=session_options,
    providers=["CPUExecutionProvider"]
)

input_name = session.get_inputs()[0].name

# =========================================================
# CAMERA MEMORY
# =========================================================

camera_buffers = {}
camera_locks = {}
camera_last_seen = {}

last_prediction_debug = {}

# =========================================================
# UTILITIES
# =========================================================

def is_model_loaded():
    return session is not None


def warmup_model():

    dummy_input = np.zeros(
        (1, SEQ_LEN, IMG_SIZE, IMG_SIZE, 1),
        dtype=np.float32
    )

    session.run(None, {input_name: dummy_input})

    logger.info("ONNX model warmup complete")

    return True


def _cleanup_camera_state(now=None, *, force=False):
    now = now or time.time()

    stale_camera_ids = [
        camera_id
        for camera_id, last_seen in camera_last_seen.items()
        if now - last_seen > CAMERA_STATE_TTL_SECONDS
    ]

    if force and not stale_camera_ids and len(camera_last_seen) > MAX_CAMERA_STATES:
        overflow = len(camera_last_seen) - MAX_CAMERA_STATES
        stale_camera_ids = sorted(
            camera_last_seen,
            key=camera_last_seen.get,
        )[:overflow]

    for camera_id in stale_camera_ids:
        camera_buffers.pop(camera_id, None)
        camera_locks.pop(camera_id, None)
        camera_last_seen.pop(camera_id, None)
        last_prediction_debug.pop(f"camera:{camera_id}", None)


# =========================================================
# PREDICTION HELPERS
# =========================================================

def _to_probability(raw_pred):

    pred_value = float(
        np.array(raw_pred, dtype=np.float32).squeeze()
    )

    # safety fallback if logits
    if pred_value < 0.0 or pred_value > 1.0:
        pred_value = 1.0 / (1.0 + np.exp(-pred_value))
    
    return float(pred_value)


def _classify_prediction(raw_pred, source="unknown"):

    suspicious_score = _to_probability(raw_pred)

    label = (
        "Suspicious"
        if suspicious_score >= SUSPICIOUS_THRESHOLD
        else "Normal"
    )

    confidence = (
        suspicious_score
        if label == "Suspicious"
        else 1.0 - suspicious_score
    )

    # ---------------- DEBUG ----------------
    if DEBUG:
        print("\n==============================")
        print(f"SOURCE: {source}")
        print(f"RAW PREDICTION: {raw_pred}")
        print(f"SUSPICIOUS SCORE: {suspicious_score:.4f}")
        print(f"THRESHOLD: {SUSPICIOUS_THRESHOLD}")
        print(f"LABEL: {label}")
        print(f"CONFIDENCE: {confidence:.4f}")
        print("==============================\n")

    logger.info(
        "[%s] score=%.4f threshold=%.2f label=%s",
        source,
        suspicious_score,
        SUSPICIOUS_THRESHOLD,
        label,
    )

    return label, confidence, suspicious_score


def get_last_prediction_debug(source):

    return last_prediction_debug.get(source, {})


# =========================================================
# REALTIME CAMERA PREDICTION
# =========================================================

def predict_frame_multi(frame, camera_id="default"):

    if frame is None or frame.size == 0:
        return None, None

    lock = camera_locks.setdefault(
        camera_id,
        Lock()
    )

    with lock:
        now = time.time()
        camera_last_seen[camera_id] = now
        _cleanup_camera_state(now, force=True)

        buffer = camera_buffers.setdefault(
            camera_id,
            deque(maxlen=SEQ_LEN)
        )

        try:
            # grayscale
            gray_frame = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2GRAY
            )

            # resize
            gray_frame = cv2.resize(
                gray_frame,
                (IMG_SIZE, IMG_SIZE)
            )

            # normalize
            gray_frame = (
                gray_frame.astype(np.float32) / 255.0
            )

            # channel dimension
            gray_frame = np.expand_dims(
                gray_frame,
                axis=-1
            )

        except Exception:
            logger.exception(
                "Preprocessing error for camera %s",
                camera_id
            )
            return None, None

        # add frame
        buffer.append(gray_frame)

        # need full sequence
        if len(buffer) < SEQ_LEN:
            return None, None

        try:

            input_array = np.expand_dims(
                np.array(buffer, dtype=np.float32),
                axis=0
            )

            pred = session.run(
                None,
                {input_name: input_array}
            )[0]

            source = f"camera:{camera_id}"

            label, confidence, suspicious_score = (
                _classify_prediction(
                    pred,
                    source=source
                )
            )

            last_prediction_debug[source] = {
                "suspicious_score": float(suspicious_score),
                "threshold": float(SUSPICIOUS_THRESHOLD),
                "label": label,
                "confidence": float(confidence),
            }

        except Exception:
            logger.exception(
                "ONNX prediction error for camera %s",
                camera_id
            )
            return None, None

        return label, float(confidence)


# aliases
def predict_frame14(frame, camera_id="default", skip_rate=None):
    return predict_frame_multi(frame, camera_id)


def predict_frame_multi15(frame, camera_name, skip_rate=None):
    return predict_frame_multi(frame, camera_name)


# =========================================================
# VIDEO PREDICTION
# =========================================================

def run_video_prediction(
    video_path,
    stop_on_suspicious=False,
    frame_skip=2
):

    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        raise ValueError(
            f"Unable to open video file: {video_path}"
        )

    frames = deque(maxlen=SEQ_LEN)

    suspicious = 0
    normal = 0

    frame_index = 0

    first_suspicious_frame = None

    while True:

        ret, frame = cap.read()

        if not ret:
            break

        frame_index += 1

        # frame skipping
        if frame_skip > 1:
            if frame_index % frame_skip != 0:
                continue

        original_frame = frame.copy()

        try:

            # grayscale
            frame = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2GRAY
            )

            # resize
            frame = cv2.resize(
                frame,
                (IMG_SIZE, IMG_SIZE)
            )

            # normalize
            frame = (
                frame.astype(np.float32) / 255.0
            )

            # channel dimension
            frame = np.expand_dims(
                frame,
                axis=-1
            )

        except Exception:
            logger.exception(
                "Frame preprocessing error"
            )
            continue

        frames.append(frame)

        # wait for full sequence
        if len(frames) < SEQ_LEN:
            continue

        try:

            input_array = np.expand_dims(
                np.array(frames, dtype=np.float32),
                axis=0
            )

            pred = session.run(
                None,
                {input_name: input_array}
            )[0]

            label, confidence, suspicious_score = (
                _classify_prediction(
                    pred,
                    source="video"
                )
            )

            # save debug
            last_prediction_debug["video"] = {
                "suspicious_score": float(suspicious_score),
                "threshold": float(SUSPICIOUS_THRESHOLD),
                "label": label,
                "confidence": float(confidence),
            }

        except Exception:
            logger.exception(
                "ONNX prediction error"
            )
            continue

        # ---------------- voting ----------------

        if label == "Suspicious":

            suspicious += 1

            if first_suspicious_frame is None:
                first_suspicious_frame = original_frame

            if DEBUG:
                print(
                    f"[VIDEO] Suspicious vote "
                    f"{suspicious}"
                )

            # early stop
            if (
                stop_on_suspicious and
                suspicious >= MIN_SUSPICIOUS_VOTES
            ):
                break

        else:

            normal += 1

            if DEBUG:
                print(
                    f"[VIDEO] Normal vote "
                    f"{normal}"
                )

    cap.release()

    # =====================================================
    # FINAL DECISION
    # =====================================================

    if suspicious >= MIN_SUSPICIOUS_VOTES:
        final = "Suspicious"
    else:
        final = "Normal"

    # final debug
    print("\n====================================")
    print("FINAL VIDEO RESULT")
    print("------------------------------------")
    print(f"Suspicious Votes: {suspicious}")
    print(f"Normal Votes: {normal}")
    print(f"Final Label: {final}")
    print("====================================\n")

    return (
        final,
        suspicious,
        normal,
        first_suspicious_frame
    )
