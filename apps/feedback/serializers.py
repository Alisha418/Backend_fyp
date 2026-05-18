from rest_framework import serializers
from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    citizen_name = serializers.CharField(source='citizen_id.name', read_only=True)
    worker_name = serializers.CharField(source='worker_id.worker_id.name', read_only=True)
    report_pk = serializers.IntegerField(source='report_id.report_id', read_only=True)
    task_type = serializers.CharField(source='report_id.waste_type', read_only=True)
    task_location = serializers.CharField(source='report_id.location', read_only=True)
    is_positive = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    class Meta:
        model = Feedback
        fields = [
            'feedback_id',
            'report_id',
            'report_pk',
            'citizen_id',
            'citizen_name',
            'worker_id',
            'worker_name',
            'rating',
            'comment',
            'created_at',
            'task_type',
            'task_location',
            'is_positive',
            'tags',
        ]
        read_only_fields = ['feedback_id', 'created_at']

    def get_is_positive(self, obj):
        # Product rule: strictly above 3-star is positive.
        return int(obj.rating or 0) > 3

    def get_tags(self, obj):
        # Keep contract stable for app UI chip section.
        return []


class FeedbackCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ['report_id', 'citizen_id', 'worker_id', 'rating', 'comment']