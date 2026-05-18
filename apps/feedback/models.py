from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from apps.accounts.models import Account
from apps.workers.models import Worker
from apps.reports.models import Report


class Feedback(models.Model):
    feedback_id = models.AutoField(primary_key=True)
    report_id = models.OneToOneField(Report, on_delete=models.CASCADE, related_name='feedback', db_column='report_id')
    citizen_id = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='feedbacks_given', db_column='citizen_id')
    worker_id = models.ForeignKey(Worker, on_delete=models.CASCADE, related_name='feedbacks_received', db_column='worker_id')
    rating = models.SmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta: 
        db_table = 'feedback'
        ordering = ['-created_at']
        
    def __str__(self):
        return f"Feedback for Report #{self.report_id. report_id} - {self. rating}★"
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update worker's average rating
        self.worker_id.update_rating()