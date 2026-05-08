import cv2

try:
    import cloudinary.uploader
except ImportError:  # pragma: no cover - dependency may not be installed locally yet
    cloudinary = None
else:
    cloudinary = cloudinary.uploader


def upload_frame_to_cloudinary(frame, *, public_id):
    if cloudinary is None or frame is None or frame.size == 0:
        return None

    success, buffer_jpg = cv2.imencode(".jpg", frame)
    if not success:
        return None

    result = cloudinary.upload(
        buffer_jpg.tobytes(),
        folder="securevision/suspicious_frames",
        public_id=public_id,
        overwrite=True,
        resource_type="image",
    )
    return result.get("secure_url")


def upload_video_to_cloudinary(file_path, *, public_id):
    if cloudinary is None or not file_path:
        return None

    result = cloudinary.upload(
        file_path,
        folder="securevision/videos",
        public_id=public_id,
        overwrite=True,
        resource_type="video",
    )
    return result.get("secure_url")
