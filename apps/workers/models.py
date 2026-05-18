from django.db import models
from apps.accounts.models import Account
from django.db.models import Avg

class Worker(models.Model):
    """Worker model - extends Account with worker-specific fields"""
    
    worker_id = models.OneToOneField(
        Account,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name='worker_profile'
    )
    employee_code = models.CharField(max_length=50, unique=True)
    total_tasks = models.IntegerField(default=0)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    is_tracking = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'workers'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.employee_code} - {self.worker_id.name}"
    
    def update_stats(self):
        """Update worker statistics from completed reports"""
        from apps.reports.models import Report
        from apps.feedback.models import Feedback
        from django.db.models import Avg
        
        # Get total resolved tasks
        resolved = Report.objects.filter(worker_id=self, status='Resolved')
        self.total_tasks = resolved.count()
        
        # Get average rating from Feedback model (not Report model)
        avg_rating = Feedback.objects.filter(worker_id=self).aggregate(Avg('rating'))['rating__avg']
        self.avg_rating = round(avg_rating, 2) if avg_rating else 0.00
        
        self.save(update_fields=['total_tasks', 'avg_rating'])
    
    def update_rating(self):
        """Update worker's average rating from feedbacks"""
        from apps.feedback.models import Feedback
        avg_rating = Feedback.objects.filter(worker_id=self).aggregate(Avg('rating'))['rating__avg']
        if avg_rating:
            self.avg_rating = round(avg_rating, 2)
            self.save(update_fields=['avg_rating'])


class WorkerLocation(models.Model):
    """Track worker GPS locations"""
    
    location_id = models.AutoField(primary_key=True)
    worker_id = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name='locations'
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    recorded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta: 
        db_table = 'worker_location'
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['worker_id', '-recorded_at']),
        ]
    
    def __str__(self):
        return f"{self.worker_id.employee_code} @ {self.recorded_at}"


class WorkerMonthlyStats(models.Model):
    """Monthly performance statistics for workers"""
    
    stat_id = models.AutoField(primary_key=True)
    worker_id = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name='monthly_stats'
    )
    month = models.DateField()
    resolved_tasks = models.IntegerField(default=0)
    avg_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    badge = models.CharField(
        max_length=20,
        choices=[
            ('Bronze', 'Bronze'),
            ('Silver', 'Silver'),
            ('Gold', 'Gold'),
            ('Diamond', 'Diamond'),
        ],
        default='Bronze'
    )
    points = models.IntegerField(default=0)
    monthly_rank = models.IntegerField(null=True, blank=True)
    
    class Meta:
        db_table = 'workers_worker_monthly_stats'
        unique_together = ('worker_id', 'month')
        ordering = ['-month']
    
    def __str__(self):
        return f"{self.worker_id.employee_code} - {self.month.strftime('%Y-%m')}"


class WorkerBadgeHistory(models.Model):
    """Badge history timeline for each worker."""

    BADGE_CHOICES = [
        ("Bronze", "Bronze"),
        ("Silver", "Silver"),
        ("Gold", "Gold"),
        ("Diamond", "Diamond"),
    ]

    history_id = models.AutoField(primary_key=True)
    worker_id = models.ForeignKey(
        Worker,
        on_delete=models.CASCADE,
        related_name="badge_history",
    )
    badge = models.CharField(max_length=20, choices=BADGE_CHOICES)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "Badge_History"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["worker_id", "-started_at"]),
            models.Index(fields=["worker_id", "is_current"]),
        ]

    def __str__(self):
        return f"{self.worker_id.employee_code} {self.badge} ({self.started_at})"
