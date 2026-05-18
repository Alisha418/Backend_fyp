from rest_framework import serializers
import json
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer with enhanced fields for permanent storage:
    - Uses database fields (title, status, expires_at, etc.) when available
    - Falls back to message JSON for backward compatibility
    """
    title = serializers.SerializerMethodField()
    type = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    formatted_message = serializers.SerializerMethodField()  # ✅ Readable message for admin panel
    
    class Meta: 
        model = Notification
        fields = [
            'notification_id',
            'recipient_type',
            'recipient_id',
            'message',
            'title',
            'type',
            'data',
            'formatted_message',  # ✅ Readable message format
            'is_read',
            'created_at',
            # ✅ New fields
            'status',
            'expires_at',
            'task_number',
            'accepted_at',
            'report_id',
        ]
        read_only_fields = ['notification_id', 'created_at']
    
    def _parse_message_data(self, obj):
        try:
            if obj.message:
                return json.loads(obj.message)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return {}

    def _is_from_admin_message(self, message_data: dict) -> bool:
        if not message_data:
            return False
        if message_data.get('from_admin') is True:
            return True
        if str(message_data.get('source') or '').lower() == 'admin_panel':
            return True
        reported_by = str(message_data.get('reported_by') or '').lower()
        return 'admin' in reported_by

    def get_title(self, obj):
        """Get title from database field, fallback to message JSON"""
        message_data = self._parse_message_data(obj)
        title = (obj.title or '').strip()
        if not title:
            title = (
                message_data.get('title')
                or message_data.get('message')
                or 'Notification'
            )
        if self._is_from_admin_message(message_data):
            low = title.lower()
            if not low.startswith('from admin'):
                title = f'From Admin — {title}'
        return title
    
    def get_type(self, obj):
        """Extract type from message JSON"""
        try:
            if obj.message:
                message_data = json.loads(obj.message)
                notification_type = message_data.get('type', 'general')
                # Map backend types to frontend types
                type_map = {
                    'report_available': 'task_assignment',  # Worker - citizen submitted report
                    'task_assignment': 'task_assignment',  # Worker - admin assigned task
                    'citizen_report_pending': 'citizen_report_pending',
                    'work_completed': 'work_completed',
                    'work_started': 'work_started',
                    'report_assigned': 'report_assigned',  # Citizen
                    'report_declined': 'report_rejected',  # Citizen
                    'report_resolved': 'report_resolved',  # Citizen
                    'report_in_progress': 'report_in_progress',  # Citizen
                    'feedback': 'feedback_received',  # Worker - feedback received
                    'admin_message': 'admin_message',
                }
                return type_map.get(notification_type, notification_type)
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        return 'general'
    
    def get_data(self, obj):
        """Parse message JSON as data, merge with database fields"""
        data = self._parse_message_data(obj)
        
        # ✅ Merge database fields into data for frontend
        if obj.report_id:
            data['report_id'] = obj.report_id
        if obj.expires_at:
            data['expires_at'] = obj.expires_at.isoformat()
        if obj.status:
            data['status'] = obj.status
        if obj.task_number:
            data['task_number'] = obj.task_number
        if obj.accepted_at:
            data['accepted_at'] = obj.accepted_at.isoformat()
        
        if self._is_from_admin_message(data):
            data['from_admin'] = True
            data['source'] = data.get('source') or 'admin_panel'
            data['reported_by'] = data.get('reported_by') or 'Assigned by Admin'
            if data.get('admin_name'):
                data['sender_label'] = f"From Admin ({data['admin_name']})"
            else:
                data['sender_label'] = 'From Admin'

        # ✅ Include reported_by from message JSON if available (for admin vs citizen distinction)
        if 'reported_by' in data:
            pass  # Already in data from message JSON
        elif obj.report_id:
            # ✅ Try to get reported_by from report if not in message
            try:
                from apps.reports.models import Report
                report = Report.objects.filter(report_id=obj.report_id).first()
                if report:
                    # Check if admin-assigned (accepted_at is None and status is 'Assigned')
                    if report.accepted_at is None and report.status == 'Assigned' and report.worker_id is not None:
                        data['reported_by'] = 'Assigned by Admin'
                    elif report.citizen_id:
                        data['reported_by'] = f'Reported by {report.citizen_id.name}'
            except Exception:
                pass  # Ignore if report not found
        
        return data
    
    def get_formatted_message(self, obj):
        """One-line human summary for admin panel (stored `message` is often JSON)."""
        if not obj.message:
            return 'No message'
        try:
            message_data = json.loads(obj.message)
        except (json.JSONDecodeError, TypeError, AttributeError):
            return obj.message

        ntype = str(message_data.get('type') or '')
        citizen = str(message_data.get('citizen_name') or 'Citizen').strip() or 'Citizen'
        report_id = message_data.get('report_id')
        waste = str(message_data.get('waste_type') or '').strip() or 'waste'
        admin = str(message_data.get('admin_name') or 'Admin').strip() or 'Admin'
        reported_by = str(message_data.get('reported_by') or '')
        short = str(message_data.get('message') or '').strip()

        report_bit = f"Report #{report_id}" if report_id is not None else 'A report'
        worker_name = str(message_data.get('worker_name') or '').strip()
        worker_label = worker_name or 'this worker'

        if ntype == 'citizen_report_pending':
            n_workers = message_data.get('workers_notified_count')
            extra = f" ({n_workers} workers notified)." if isinstance(n_workers, int) else ''
            return (
                f"{citizen} submitted {report_bit} ({waste}). "
                f"Waiting for a worker to accept.{extra}"
            )

        if ntype == 'work_completed':
            return f"{citizen} — {report_bit} ({waste}) completed by {worker_label}."

        if ntype == 'work_started':
            return f"{citizen} — {report_bit} ({waste}). {worker_label} started work."

        if ntype == 'admin_message':
            return f"From Admin ({admin}): {short or 'New message for worker.'}"

        if ntype in ('task_assignment', 'report_available'):
            admin_led = message_data.get('from_admin') or 'admin' in reported_by.lower()
            if admin_led:
                return (
                    f"From Admin ({admin}) — {report_bit} ({waste}) assigned to {worker_label}."
                )
            return (
                f"{citizen} — {report_bit} ({waste}). "
                f"{worker_label} was notified to accept or decline."
            )

        if short:
            return short

        # Other structured types: compact line instead of full JSON
        parts = [f"{k}: {v}" for k, v in message_data.items() if k not in ('type',) and v]
        return ' · '.join(parts[:6]) if parts else obj.message


class SendNotificationSerializer(serializers.Serializer):
    """For POST /api/workers/{id}/notify/"""
    title = serializers.CharField(max_length=255, required=False, default='Notification')
    body = serializers.CharField(required=True)

    def validate_body(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("Message body cannot be empty")
        return value.strip()