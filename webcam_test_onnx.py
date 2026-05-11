import cv2

from detection.ml.pridict_gray import (
    get_last_prediction_debug,
    predict_frame_multi,
)


def main():
    cap = cv2.VideoCapture(0)

    if not cap.isOpened():
        raise RuntimeError("Could not open webcam")

    camera_id = "local-webcam"

    print("Press 'q' to quit")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        label, confidence = predict_frame_multi(frame, camera_id)
        debug = get_last_prediction_debug(f"camera:{camera_id}")

        display = frame.copy()

        if label is None:
            status_text = "Buffering..."
            color = (0, 255, 255)
        else:
            score = debug.get("score", 0.0)
            raw_label = debug.get("raw_label", label)
            live_votes = debug.get("live_votes", 0)
            live_window = debug.get("live_window", 0)
            status_text = (
                f"{label} | conf={confidence:.2f} | "
                f"score={score:.4f} | raw={raw_label} | "
                f"votes={live_votes}/{live_window}"
            )
            color = (0, 0, 255) if label == "Suspicious" else (0, 255, 0)

        cv2.putText(
            display,
            status_text,
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            color,
            2,
            cv2.LINE_AA,
        )

        cv2.imshow("ONNX Webcam Test", display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
