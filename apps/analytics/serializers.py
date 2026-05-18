from rest_framework import serializers
from .models import UserMonthlyStats, WorkerMonthlyStats, SystemMetrics


class UserMonthlyStatsSerializer(serializers.ModelSerializer):
    """Serializer for citizen monthly statistics"""
    user_name = serializers.CharField(source='user_id.name', read_only=True)
    user_email = serializers.CharField(source='user_id.email', read_only=True)
    
    class Meta:
        model = UserMonthlyStats
        fields = '__all__'
        read_only_fields = ['stat_id', 'updated_at']


class WorkerMonthlyStatsSerializer(serializers.ModelSerializer):
    """Serializer for worker monthly statistics"""
    worker_name = serializers.CharField(source='worker_id.worker_id.name', read_only=True)
    employee_code = serializers.CharField(source='worker_id.employee_code', read_only=True)
    
    class Meta: 
        model = WorkerMonthlyStats
        fields = '__all__'
        read_only_fields = ['stat_id', 'updated_at']


class SystemMetricsSerializer(serializers.ModelSerializer):
    """Serializer for system metrics"""
    
    class Meta:
        model = SystemMetrics
        fields = '__all__'
        read_only_fields = ['metric_id', 'created_at']


class DashboardStatsSerializer(serializers.Serializer):
    """Serializer for dashboard overview statistics"""
    reports = serializers.DictField()
    workers = serializers.DictField()
    citizens = serializers.DictField()
    today = serializers.DictField()
    performance = serializers.DictField()


class TopCitizenSerializer(serializers. Serializer):
    """Serializer for top citizen leaderboard"""
    account_id = serializers.IntegerField()
    name = serializers.CharField()
    email = serializers.EmailField()
    reports = serializers.IntegerField()
    verified_reports = serializers.IntegerField()
    badge = serializers.CharField()
    points = serializers.IntegerField()
    rank = serializers.IntegerField()


class TopWorkerSerializer(serializers.Serializer):
    """Serializer for top worker leaderboard"""
    worker_id = serializers.IntegerField()
    name = serializers.CharField()
    employee_code = serializers.CharField()
    tasks_completed = serializers.IntegerField()
    avg_rating = serializers.FloatField()
    performance_score = serializers.IntegerField()
    badge = serializers.CharField()
    rank = serializers.IntegerField()


class TrendDataSerializer(serializers.Serializer):
    """Serializer for trend chart data"""
    date = serializers.CharField()
    reports = serializers.IntegerField()
    resolved = serializers.IntegerField()
    pending = serializers.IntegerField()


class ZoneAnalyticsSerializer(serializers. Serializer):
    """Serializer for zone-wise analytics"""
    zone = serializers.CharField()
    total_reports = serializers.IntegerField()
    pending = serializers.IntegerField()
    resolved = serializers.IntegerField()
    avg_resolution_time = serializers.FloatField()
    active_workers = serializers.IntegerField()


class WasteTypeAnalyticsSerializer(serializers. Serializer):
    """Serializer for waste type analytics"""
    waste_type = serializers. CharField()
    count = serializers.IntegerField()
    percentage = serializers.FloatField()
    trend = serializers.CharField()