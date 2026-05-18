from typing import List, Optional
from django.db import transaction
from django.utils import timezone
from .models import Notification, RecipientType, NotificationStatus
from .display_window import within_notification_display_window


class NotificationService: 
    """Service for notification operations"""

    @staticmethod
    def create_notification(
        recipient_type: str,
        recipient_id: int,
        message: str,
        title: str = None,
        data: dict = None
    ) -> Notification:
        """Create a single notification"""
        notification = Notification.objects.create(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            message=message,
            title=title or 'Notification',
            is_read=False,
        )
        return notification

    @staticmethod
    def get_notifications(
        recipient_type: str,
        recipient_id: int,
        unread_only: bool = False,
        limit: int = 50
    ) -> List[Notification]: 
        """Get notifications for a recipient"""
        queryset = Notification. objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id
        )
        
        if unread_only:
            queryset = queryset.filter(is_read=False)
        
        return list(queryset.order_by('-created_at')[:limit])

    @staticmethod
    def get_unread_count(recipient_type:  str, recipient_id: int) -> int:
        """Get unread count"""
        qs = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        )
        return within_notification_display_window(qs).count()

    @staticmethod
    def mark_as_read(notification_ids: List[int]) -> int:
        """Mark specific notifications as read"""
        return Notification.objects. filter(
            notification_id__in=notification_ids
        ).update(is_read=True)

    @staticmethod
    def mark_all_as_read(recipient_type: str, recipient_id: int) -> int:
        """Mark all as read for recipient"""
        qs = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            is_read=False,
        )
        return within_notification_display_window(qs).update(is_read=True)

    @staticmethod
    def send_to_worker(worker_id:  int, title: str, body: str, data:  dict = None) -> Notification:
        """Convenience method for sending to worker"""
        return NotificationService.create_notification(
            recipient_type=RecipientType. WORKER,
            recipient_id=worker_id,
            message=body,
            title=title,
            data=data
        )
    
    @staticmethod
    def mark_expired_notifications() -> int:
        """Mark all pending notifications as expired if expires_at has passed"""
        now = timezone.now()
        expired_count = Notification.objects.filter(
            status=NotificationStatus.PENDING,
            expires_at__lt=now,
            expires_at__isnull=False
        ).update(
            status=NotificationStatus.EXPIRED,
            title='Timer Expired'
        )
        return expired_count