import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Notification

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Notification)
def push_on_notification_created(sender, instance, created, **kwargs):
    if not created:
        return
    try:
        from .push import send_push_for_notification

        send_push_for_notification(instance)
    except Exception as exc:
        logger.warning(
            'Push hook failed for notification %s: %s',
            getattr(instance, 'notification_id', '?'),
            exc,
        )
