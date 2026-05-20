import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

import requests


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
    frame_url = getattr(alert, "frame_url", None)
    frame_text = frame_url or "Not available"
    created_at = getattr(alert, "created_at", None)
    created_text = created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "Unknown time"

    subject = f"SecureVision Alert: Suspicious activity on {camera_name}"
    message = (
        f"Suspicious activity was detected.\n\n"
        f"Camera: {camera_name}\n"
        f"Confidence: {confidence:.2f}\n"
        f"Detected at: {created_text}\n"
        f"Saved frame: {frame_text}\n"
    )
    html_message = (
        "<p>Suspicious activity was detected.</p>"
        f"<p><strong>Camera:</strong> {camera_name}<br>"
        f"<strong>Confidence:</strong> {confidence:.2f}<br>"
        f"<strong>Detected at:</strong> {created_text}</p>"
    )
    if frame_url:
        html_message += (
            f'<p><strong>Saved frame:</strong> <a href="{frame_url}">{frame_url}</a></p>'
            f'<p><img src="{frame_url}" alt="Suspicious frame" style="max-width:100%;height:auto;" /></p>'
        )
    else:
        html_message += "<p><strong>Saved frame:</strong> Not available</p>"

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        email.attach_alternative(html_message, "text/html")
        if frame_url:
            try:
                response = requests.get(frame_url, timeout=10)
                response.raise_for_status()
                email.attach("suspicious-frame.jpg", response.content, "image/jpeg")
            except Exception:
                logger.exception(
                    "Failed to attach suspicious frame for alert %s",
                    getattr(alert, "id", None),
                )
        email.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("Failed to send suspicious detection email for alert %s", getattr(alert, "id", None))
        return False
