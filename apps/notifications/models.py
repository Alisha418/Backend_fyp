from django. db import models
from django.utils import timezone


class RecipientType(models.TextChoices):
    WORKER = 'worker', 'Worker'
    CITIZEN = 'citizen', 'Citizen'
    ADMIN = 'admin', 'Admin'


class NotificationStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    DECLINED = 'declined', 'Declined'
    EXPIRED = 'expired', 'Expired'


class Notification(models.Model):
    """
    Notification model with enhanced fields for permanent storage:
    - notification_id (bigint)
    - recipient_type (character)
    - recipient_id (integer)
    - message (text) - JSON string for backward compatibility
    - is_read (boolean)
    - created_at (timestamp)
    - title (character) - Permanent title storage
    - status (character) - pending, accepted, declined, expired
    - expires_at (timestamp) - Timer expiry time
    - task_number (integer) - Task number when accepted
    - accepted_at (timestamp) - Acceptance time
    - report_id (integer) - Direct reference to report
    """
    notification_id = models.BigAutoField(primary_key=True)
    recipient_type = models.CharField(
        max_length=20,
        choices=RecipientType.choices,
        default=RecipientType. WORKER
    )
    recipient_id = models.IntegerField(db_index=True)
    message = models.TextField()  # This will store both title and body (JSON for backward compatibility)
    is_read = models.BooleanField(default=False)
    created_at = models. DateTimeField(default=timezone.now)
    
    # ✅ New fields for permanent storage
    title = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=NotificationStatus.choices,
        default=NotificationStatus.PENDING,
        null=True,
        blank=True,
        db_index=True
    )
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    task_number = models.IntegerField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    report_id = models.IntegerField(null=True, blank=True, db_index=True)

    class Meta: 
        db_table = 'notifications'
        ordering = ['-created_at']
        managed = False  # Don't let Django manage this table

    def __str__(self):
        return f"Notification {self. notification_id} → {self.recipient_type}:{self.recipient_id}"

    def mark_as_read(self):
        self.is_read = True
        self. save(update_fields=['is_read'])
    
    def mark_as_expired(self):
        """Mark notification as expired if expires_at has passed"""
        if self.expires_at and self.expires_at < timezone.now() and self.status == NotificationStatus.PENDING:
            self.status = NotificationStatus.EXPIRED
            if not self.title or self.title == 'Notification':
                self.title = 'Timer Expired'
            self.save(update_fields=['status', 'title'])