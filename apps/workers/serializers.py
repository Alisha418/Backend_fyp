from rest_framework import serializers
import re
from django. db.models import Avg
from django.utils import timezone
from datetime import timedelta

from .models import Worker, WorkerLocation, WorkerMonthlyStats
from apps.accounts.models import Account
from apps.accounts.media_url import build_media_file_url
from apps.reports.models import Report
from apps.feedback.models import Feedback


# =========================
# WORKER LIST SERIALIZER
# =========================

class WorkerListSerializer(serializers.ModelSerializer):
    """Serializer for worker list view"""

    account_id = serializers.IntegerField(source='worker_id.account_id', read_only=True)
    name = serializers.CharField(source='worker_id.name', read_only=True)
    email = serializers.EmailField(source='worker_id.email', read_only=True)
    phone_number = serializers.CharField(source='worker_id.phone_number', read_only=True)
    
    # ✅ FIXED: Use SerializerMethodField to handle both string and ImageField
    profile_image = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source='worker_id.is_active', read_only=True)

    class Meta:
        model = Worker
        fields = [
            'worker_id',
            'employee_code',
            'total_tasks',
            'avg_rating',
            'is_tracking',
            'created_at',
            'updated_at',
            'account_id',
            'name',
            'email',
            'phone_number',
            'profile_image',
            'is_active'
        ]
    
    def get_profile_image(self, obj):
        request = self.context.get('request')
        return build_media_file_url(obj.worker_id.profile_image, request)


# =========================
# WORKER DETAIL SERIALIZER
# =========================

class WorkerDetailSerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()
    current_assignments = serializers.SerializerMethodField()
    monthly_performance = serializers.SerializerMethodField()
    lifetime_avg_rating = serializers.SerializerMethodField()

    class Meta:
        model = Worker
        fields = '__all__'

    def get_account(self, obj):
        request = self.context.get('request')
        profile_image_url = build_media_file_url(obj.worker_id.profile_image, request)

        return {
            'account_id': obj.worker_id. account_id,
            'name': obj.worker_id.name,
            'email': obj. worker_id.email,
            'phone_number': obj.worker_id.phone_number,
            'profile_image': profile_image_url,
            'is_active': obj.worker_id.is_active,
            'created_at': obj.worker_id.created_at,
        }

    def get_current_assignments(self, obj):
        return Report.objects.filter(
            worker_id=obj,
            status__in=['Assigned', 'In Progress']
        ).count()

    def get_monthly_performance(self, obj):
        thirty_days_ago = timezone.now() - timedelta(days=30)

        reports = Report.objects.filter(
            worker_id=obj,
            submitted_at__gte=thirty_days_ago,
            status='Resolved'
        )

        avg_rating = Feedback.objects.filter(
            worker_id=obj,
            report_id__in=reports
        ).aggregate(avg=Avg('rating'))['avg'] or 0

        return {
            'resolved_count': reports.count(),
            'avg_rating': float(avg_rating),
        }

    def get_lifetime_avg_rating(self, obj):
        avg_rating = Feedback.objects. filter(
            worker_id=obj
        ).aggregate(avg=Avg('rating'))['avg'] or 0

        return float(avg_rating)


# =========================
# WORKER CREATE SERIALIZER
# =========================

class WorkerCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True, min_length=8)
    employee_code = serializers.CharField(max_length=50)
    
    # ✅ ADD IMAGE FIELD FOR CREATION
    profile_image = serializers.ImageField(required=False, allow_null=True)

    def validate_email(self, value):
        value = value.lower().strip()
        if Account.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_employee_code(self, value):
        value = value.strip()
        if Worker.objects.filter(employee_code=value).exists():
            raise serializers.ValidationError("A worker with this employee code already exists.")
        return value

    def validate_phone(self, value: str):
        # On create, phone is optional, but if provided must be valid +92 format.
        raw = (value or '').strip()
        if not raw:
            return ''

        # Keep '+' only at the start, then remove non-digits.
        digits = re.sub(r'\D', '', raw)

        # Handle common local formats:
        # - +92XXXXXXXXXX  (digits: 92 + 10 digits)
        # - 0XXXXXXXXXX     (digits: 0 + 10 digits)
        if digits.startswith('92') and len(digits) == 12:
            normalized = '+92' + digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            normalized = '+92' + digits[1:]
        else:
            raise serializers.ValidationError('Phone number must be in +92 format (e.g., +923001234567)')

        if not re.match(r'^\+92\d{10}$', normalized):
            raise serializers.ValidationError('Phone number must be in +92 format')

        return normalized

    def create(self, validated_data):
        from django.db import transaction

        password = validated_data.pop('password')
        profile_image = validated_data.pop('profile_image', None)

        with transaction.atomic():
            account = Account.objects.create_user(
                email=validated_data['email'],
                password=password,
                name=validated_data['name'],
                phone_number=validated_data.get('phone', ''),
                role='worker',
                is_active=True
            )
            
            # ✅ SAVE PROFILE IMAGE
            if profile_image:
                account.profile_image = profile_image
                account.save()

            worker = Worker.objects.create(
                worker_id=account,
                employee_code=validated_data['employee_code']
            )

            return worker


# =========================
# WORKER UPDATE SERIALIZER
# =========================

class WorkerUpdateSerializer(serializers. Serializer):
    name = serializers.CharField(max_length=150, required=False)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
 
    def validate_phone(self, value: str):
        raw = (value or '').strip()

        # For edit profile, we want phone to be present + valid.
        if not raw:
            raise serializers.ValidationError('Phone number is required')

        digits = re.sub(r'\D', '', raw)
        if digits.startswith('92') and len(digits) == 12:
            normalized = '+92' + digits[2:]
        elif digits.startswith('0') and len(digits) == 11:
            normalized = '+92' + digits[1:]
        else:
            raise serializers.ValidationError('Phone number must be in +92 format (e.g., +923001234567)')

        if not re.match(r'^\+92\d{10}$', normalized):
            raise serializers.ValidationError('Phone number must be in +92 format')

        return normalized

    def update(self, instance, validated_data):
        from django.db import transaction
        from apps.tracking.models import ActivityLog

        request = self.context.get('request')
        admin_id = getattr(getattr(request, 'user', None), 'id', 0)

        with transaction.atomic():
            # ✅ UPDATE ACCOUNT FIELDS
            if 'name' in validated_data:
                instance.worker_id.name = validated_data['name']
            if 'phone' in validated_data:
                instance.worker_id.phone_number = validated_data['phone']

            instance.worker_id.save(update_fields=['name', 'phone_number'])
            instance.save()

            # ✅ LOG ACTIVITY
            try:
                ActivityLog.objects.create(
                    activity_type='worker_updated',
                    description=f'Worker {instance.employee_code} profile updated (name/phone)',
                    actor_id=admin_id,
                    target_type='worker',
                    target_id=instance.worker_id. account_id
                )
            except Exception:
                pass

            return instance


# =========================
# WORKER LOCATION SERIALIZER
# =========================

class WorkerLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkerLocation
        fields = '__all__'


# =========================
# WORKER MONTHLY STATS
# =========================

class WorkerMonthlyStatsSerializer(serializers.ModelSerializer):
    worker_name = serializers.CharField(source='worker_id.worker_id.name', read_only=True)
    employee_code = serializers.CharField(source='worker_id.employee_code', read_only=True)

    class Meta:
        model = WorkerMonthlyStats
        fields = '__all__'