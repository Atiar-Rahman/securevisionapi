import cv2
import logging

logger = logging.getLogger(__name__)

try:
    import cloudinary
    import cloudinary.uploader
    import cloudinary.api_client.call_api as cloudinary_call_api
    from cloudinary.utils import get_http_connector
except ImportError:  # pragma: no cover - dependency may not be installed locally yet
    cloudinary = None
else:
    def _init_cloudinary_http_pool():
        """Initialize Cloudinary's shared HTTP connector with a larger connection pool."""
        try:
            pool_options = {"num_pools": 10, "maxsize": 10}
            cloudinary_call_api._http = get_http_connector(cloudinary.config(), pool_options)
            logger.info("Initialized Cloudinary HTTP pool: num_pools=%s maxsize=%s", pool_options["num_pools"], pool_options["maxsize"])
        except Exception as e:
            logger.warning("Unable to initialize Cloudinary HTTP pool: %s", e)

    _init_cloudinary_http_pool()


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
