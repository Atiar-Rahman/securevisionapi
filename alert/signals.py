import logging

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Alert
from detection.notifications import send_suspicious_detection_email

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Alert)
def send_email_for_suspicious_alert(sender, instance, created, **kwargs):
    if not created:
        return

    if instance.alert_type != "suspicious":
        return

    if not getattr(settings, "SUSPICIOUS_EMAIL_ENABLED", False):
        logger.debug(
            "Suspicious email disabled, skipping email for alert %s",
            instance.pk,
        )
        return

    try:
        send_suspicious_detection_email(instance)
    except Exception:
        logger.exception(
            "Failed to send suspicious alert email for alert %s",
            instance.pk,
        )
