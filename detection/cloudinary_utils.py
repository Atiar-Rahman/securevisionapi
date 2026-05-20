import cv2
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

logger = logging.getLogger(__name__)

try:
    import cloudinary
    import cloudinary.uploader
except ImportError:  # pragma: no cover - dependency may not be installed locally yet
    cloudinary = None
else:
    # Configure session with connection pooling and retry strategy
    def _get_requests_session():
        """Create a requests session with connection pooling and retry strategy."""
        session = requests.Session()
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST", "GET"],
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=5,
            pool_maxsize=5,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    cloudinary_session = _get_requests_session()


UPLOAD_TIMEOUT = 30  # seconds
MAX_UPLOAD_RETRIES = 2


def upload_frame_to_cloudinary(frame, *, public_id):
    if cloudinary is None or frame is None or frame.size == 0:
        logger.warning("Cloudinary upload skipped: cloudinary not available or frame is empty")
        return None

    success, buffer_jpg = cv2.imencode(".jpg", frame)
    if not success:
        logger.error("Failed to encode frame to JPG for public_id %s", public_id)
        return None

    retry_count = 0
    while retry_count <= MAX_UPLOAD_RETRIES:
        try:
            result = cloudinary.uploader.upload(
                buffer_jpg.tobytes(),
                folder="securevision/suspicious_frames",
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                timeout=UPLOAD_TIMEOUT,
            )
            return result.get("secure_url")
        except Exception as e:
            retry_count += 1
            if retry_count <= MAX_UPLOAD_RETRIES:
                logger.warning(
                    "Cloudinary upload attempt %d failed for %s: %s. Retrying...",
                    retry_count,
                    public_id,
                    str(e),
                )
            else:
                logger.error(
                    "Cloudinary upload failed for %s after %d retries: %s",
                    public_id,
                    MAX_UPLOAD_RETRIES,
                    str(e),
                )
                return None
