"""
Management command to mark expired notifications
Run: python manage.py mark_expired_notifications
Can be scheduled via cron or celery beat
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from apps.notifications.models import Notification, NotificationStatus


class Command(BaseCommand):
    help = 'Mark notifications as expired if expires_at has passed'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Find all pending notifications that have expired
        expired_notifications = Notification.objects.filter(
            status=NotificationStatus.PENDING,
            expires_at__lt=now,
            expires_at__isnull=False
        )
        
        count = 0
        for notification in expired_notifications:
            notification.status = NotificationStatus.EXPIRED
            if not notification.title or notification.title == 'Notification':
                notification.title = 'Timer Expired'
            notification.save(update_fields=['status', 'title'])
            count += 1
        
        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully marked {count} notification(s) as expired'
                )
            )
        else:
            self.stdout.write('No expired notifications found')

