"""How far back notification lists/counts are shown in the app and admin panel."""

from datetime import timedelta

from django.utils import timezone

# Shown to worker, citizen, and admin UIs (list + unread badge).
NOTIFICATION_DISPLAY_DAYS = 30


def notification_display_cutoff():
    return timezone.now() - timedelta(days=NOTIFICATION_DISPLAY_DAYS)


def within_notification_display_window(queryset):
    """Restrict queryset to notifications created in the last 30 days."""
    return queryset.filter(created_at__gte=notification_display_cutoff())
