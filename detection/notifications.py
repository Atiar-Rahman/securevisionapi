import logging

from django.conf import settings
from django.core.mail import send_mail


logger = logging.getLogger(__name__)


def send_suspicious_detection_email(alert):
    if not getattr(settings, "SUSPICIOUS_EMAIL_ENABLED", False):
        return False

    user = getattr(alert, "user", None)
    camera = getattr(alert, "camera", None)
    recipient = getattr(user, "email", None)

    if not recipient:
        return False

    camera_name = getattr(camera, "name", "Unknown camera")
    confidence = getattr(alert, "confidence", 0)
    frame_url = getattr(alert, "frame_url", None) or "Not available"
    created_at = getattr(alert, "created_at", None)
    created_text = created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "Unknown time"

    subject = f"SecureVision Alert: Suspicious activity on {camera_name}"
    message = (
        f"Suspicious activity was detected.\n\n"
        f"Camera: {camera_name}\n"
        f"Confidence: {confidence:.2f}\n"
        f"Detected at: {created_text}\n"
        f"Saved frame: {frame_url}\n"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception("Failed to send suspicious detection email for alert %s", getattr(alert, "id", None))
        return False
