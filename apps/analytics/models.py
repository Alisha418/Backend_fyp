from django.db import models
from django.utils import timezone


class UserMonthlyStats(models.Model):
    """Monthly statistics for citizens"""
    stat_id = models.AutoField(primary_key=True)
    month_year = models.CharField(max_length=7)
    verified_reports = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'user_monthly_stats'
        
    def __str__(self):
        return f"User Stats - {self.month_year}"


class WorkerMonthlyStats(models.Model):
    """Monthly performance statistics for workers"""
    stat_id = models.AutoField(primary_key=True)
    month_year = models.CharField(max_length=7)
    resolved_tasks = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'analytics_worker_monthly_stats'
        
    def __str__(self):
        return f"Worker Stats - {self.month_year}"


class SystemMetrics(models.Model):
    """Daily system-wide metrics"""
    metric_id = models.BigAutoField(primary_key=True)
    date = models.DateField(unique=True, db_index=True)
    total_reports = models.IntegerField(default=0)
    pending_reports = models.IntegerField(default=0)
    resolved_reports = models.IntegerField(default=0)
    avg_resolution_time = models.FloatField(default=0.0)
    active_citizens = models.IntegerField(default=0)
    active_workers = models.IntegerField(default=0)
    new_registrations = models.IntegerField(default=0)
    system_uptime = models.FloatField(default=100.0)
    avg_response_time = models.FloatField(default=0.0)
    ai_accuracy = models.FloatField(default=0.0)
    ai_verifications = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta: 
        db_table = 'system_metrics'
        ordering = ['-date']
        verbose_name = 'System Metric'
        verbose_name_plural = 'System Metrics'
        
    def __str__(self):
        return f"Metrics for {self.date}"