from django.db import models


class ActivityLog(models.Model):
    """
    ACTIVITY_LOG table - Security Audit
    Logs every major action for accountability
    """
    
    # Unique record for audit trail
    log_id = models.BigAutoField(primary_key=True)
    
    # Who performed the action
    actor_type = models.CharField(
        max_length=20,
        choices=[
            ('Citizen', 'Citizen'),
            ('Worker', 'Worker'),
            ('Admin', 'Admin'),
        ]
    )
    
    # The ID of the person who did it
    actor_id = models. IntegerField(null=False)
    
    # The verb (e.g., 'CREATED', 'DELETED', 'UPDATED')
    action = models.CharField(max_length=255, null=False)
    
    # The object type (e.g., 'Account', 'Report', 'System_Config')
    target_type = models.CharField(max_length=50, null=False)
    
    # The ID of the specific object affected
    target_id = models. IntegerField(null=True, blank=True)
    
    # Human-readable details
    description = models.TextField(null=True, blank=True)
    
    # When the event happened
    created_at = models. DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'activity_log'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.actor_type} {self.action} {self.target_type} - {self.created_at}"