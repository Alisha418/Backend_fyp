from rest_framework import viewsets, status
from rest_framework. decorators import action
from rest_framework. response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework. parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.views import APIView
from django.db.models import Q, Count, Avg, F
from django.db import models
from django.core.mail import send_mail
from django.conf import settings
from django.utils. crypto import get_random_string
from django.utils import timezone
from datetime import date, datetime, time
from decimal import Decimal
import uuid as uuid_lib
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework_simplejwt.authentication import JWTAuthentication
from . models import Worker, WorkerLocation, WorkerMonthlyStats
from apps.admins.permissions import IsAdmin
from apps.admins.authentication import AdminJWTAuthentication
from . serializers import (
    WorkerListSerializer,
    WorkerDetailSerializer,
    WorkerCreateSerializer,
    WorkerUpdateSerializer,
    WorkerLocationSerializer,
    WorkerMonthlyStatsSerializer
)
from .profile_summary_service import (
    get_worker_for_user,
    build_profile_summary_payload,
)
from .badge_history_service import (
    calculate_rankings_snapshot,
    sync_badge_history_from_rankings,
)
import logging

logger = logging.getLogger(__name__)


def _coerce_json_value(value):
    """
    DRF JSONRenderer cannot encode Decimal, UUID, datetime, etc. Coerce to primitives.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid_lib.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _coerce_json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_json_value(x) for x in value]
    return str(value)


def _rankings_json_safe(entries):
    """
    Ranking rows from calculate_rankings_snapshot() include a 'worker' ORM key for
    sync_badge_history_from_rankings(). JSON cannot encode Django models — strip before Response.
    Also coerce Decimal/UUID/etc. so DRF does not raise TypeError when rendering JSON.
    """
    safe = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        row = {
            k: _coerce_json_value(v)
            for k, v in entry.items()
            if k != "worker"
        }
        safe.append(row)
    return safe


class WorkerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Worker CRUD operations
    ✅ WITH IMAGE UPLOAD SUPPORT
    ✅ WITH PASSWORD RESET EMAIL
    ✅ WITH PUSH NOTIFICATIONS
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    
    # ✅ ADD PARSERS FOR FILE UPLOAD
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    
    # Filtering
    filterset_fields = ['is_tracking', 'worker_id__is_active']
    
    # Searching
    search_fields = ['employee_code', 'worker_id__name', 'worker_id__email']
    
    # Ordering
    ordering_fields = ['total_tasks', 'avg_rating', 'worker_id__name']
    ordering = ['-avg_rating']
    
    def get_queryset(self):
        """Get workers with optional filters"""
        queryset = Worker.objects. select_related('worker_id').all()
        
        # Filter by active status
        is_active = self. request.query_params.get('is_active')
        if is_active is not None:
            is_active_bool = is_active. lower() in ['true', '1', 'yes']
            queryset = queryset.filter(worker_id__is_active=is_active_bool)
        
        # Filter by tracking status
        is_tracking = self.request. query_params.get('is_tracking')
        if is_tracking is not None: 
            is_tracking_bool = is_tracking.lower() in ['true', '1', 'yes']
            queryset = queryset.filter(is_tracking=is_tracking_bool)
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer"""
        if self. action == 'list':
            return WorkerListSerializer
        elif self.action == 'retrieve':
            return WorkerDetailSerializer
        elif self.action == 'create': 
            return WorkerCreateSerializer
        elif self.action in ['update', 'partial_update']: 
            return WorkerUpdateSerializer
        return WorkerListSerializer
    
    def list(self, request, *args, **kwargs):
        """List workers with pagination"""
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer. data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success':  True,
            'count': queryset. count(),
            'results': serializer. data
        })
    
    def retrieve(self, request, *args, **kwargs):
        """Get single worker details"""
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def create(self, request, *args, **kwargs):
        """Create new worker - ✅ WITH IMAGE SUPPORT"""
        print("📸 FILES:", request.FILES)
        print("📝 DATA:", request.data)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        worker = serializer.save()
        
        detail_serializer = WorkerDetailSerializer(worker)
        return Response({
            'success': True,
            'message': 'Worker created successfully',
            'data': detail_serializer.data
        }, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        """Update worker - ✅ WITH IMAGE SUPPORT"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        print("📸 FILES:", request.FILES)
        print("📝 DATA:", request.data)
        
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        worker = serializer.save()
        
        detail_serializer = WorkerDetailSerializer(worker)
        return Response({
            'success': True,
            'message': 'Worker updated successfully',
            'data': detail_serializer.data
        })
    
    def destroy(self, request, *args, **kwargs):
        """Delete worker (cascade delete account)"""
        instance = self.get_object()
        employee_code = instance. employee_code
        
        instance.worker_id.delete()
        
        return Response({
            'success': True,
            'message': f'Worker {employee_code} deleted successfully'
        }, status=status.HTTP_200_OK)
    
    # ============================================
    # ✅ PASSWORD RESET ENDPOINT
    # ============================================
    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        """
        Send password reset email to worker
        POST /api/workers/{id}/reset_password/
        """
        worker = self.get_object()
        account = worker.worker_id
        
        if not account: 
            return Response({
                'success':  False,
                'message': 'Worker has no associated account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if not account.email:
            return Response({
                'success': False,
                'message': 'Worker has no email address configured'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # Generate a secure temporary password
            temp_password = get_random_string(
                length=12, 
                allowed_chars='abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789! @#$%'
            )
            
            # Set the temporary password
            account. set_password(temp_password)
            account.save()
            
            # Prepare email content
            subject = '🔐 Password Reset - Neat Now Cleanup System'
            
            html_message = f'''
<! DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 0; font-family:  'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a;">
    <div style="max-width:  600px; margin: 0 auto; padding: 20px;">
        <div style="background:  linear-gradient(135deg, #10b981 0%, #14b8a6 50%, #06b6d4 100%); padding: 40px 30px; border-radius: 16px 16px 0 0; text-align: center;">
            <h1 style="color:  white; margin: 0; font-size: 28px; font-weight: 700;">
                🔐 Password Reset
            </h1>
            <p style="color: rgba(255,255,255,0.9); margin:  10px 0 0 0; font-size: 14px;">
                Neat Now Cleanup System
            </p>
        </div>
        <div style="background:  #1e293b; padding: 40px 30px; border-radius: 0 0 16px 16px;">
            <p style="color: #e2e8f0; font-size: 16px; line-height: 1.6; margin:  0 0 20px 0;">
                Hello <strong style="color: #10b981;">{account.name}</strong>,
            </p>
            <p style="color: #94a3b8; font-size: 14px; line-height: 1.6; margin: 0 0 30px 0;">
                Your password has been reset by an administrator.  Please use the temporary password below to log in.
            </p>
            <div style="background:  linear-gradient(135deg, #10b981 0%, #14b8a6 100%); border-radius: 12px; padding: 3px; margin: 0 0 30px 0;">
                <div style="background: #0f172a; border-radius: 10px; padding: 25px; text-align: center;">
                    <p style="color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin: 0 0 10px 0;">
                        Your Temporary Password
                    </p>
                    <p style="color: #10b981; font-size: 28px; font-weight: 700; letter-spacing: 3px; margin: 0; font-family: 'Courier New', monospace;">
                        {temp_password}
                    </p>
                </div>
            </div>
            <div style="background: rgba(245, 158, 11, 0.1); border:  1px solid rgba(245, 158, 11, 0.3); border-radius: 8px; padding: 15px; margin: 0 0 30px 0;">
                <p style="color: #fbbf24; font-size: 14px; margin: 0;">
                    ⚠️ <strong>Important:</strong> Please change your password immediately after logging in.
                </p>
            </div>
            <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; padding: 15px;">
                <p style="color: #f87171; font-size: 13px; margin: 0;">
                    🔒 <strong>Security Notice:</strong> If you did not request this, contact your administrator immediately.
                </p>
            </div>
            <hr style="border: none; border-top: 1px solid #334155; margin: 30px 0;">
            <p style="color: #64748b; font-size: 12px; text-align: center; margin:  0;">
                This is an automated message from Neat Now Cleanup System. 
            </p>
        </div>
    </div>
</body>
</html>
            '''
            
            plain_message = f'''
Hello {account.name},

Your password has been reset by an administrator. 

Your new temporary password is: {temp_password}

IMPORTANT: Please change your password immediately after logging in. 

Best regards,
Neat Now Team
            '''
            
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL or 'rehanafzal779@gmail.com',
                recipient_list=[account.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f'✅ Password reset email sent to:  {account.email} for worker: {worker.employee_code}')
            
            return Response({
                'success': True,
                'message':  f'Password reset email sent successfully to {account.email}',
                'email':  account.email
            })
            
        except Exception as e:
            logger.error(f'❌ Failed to send password reset email to {account.email}:  {str(e)}')
            return Response({
                'success': False,
                'message': 'Failed to send password reset email.  Please check email configuration.',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # ============================================
    # ✅ SEND NOTIFICATION ENDPOINT
    # ============================================
    @action(detail=True, methods=['post'])
    def notify(self, request, pk=None):
        """
        Send push notification to worker
        POST /api/workers/{id}/notify/
        
        Request body:
        {
            "title": "Notification Title",
            "body": "Notification message",
            "data": {}  // Optional extra data
        }
        """
        worker = self.get_object()
        account = worker.worker_id
        
        body = request.data.get('body', '')
        data = request.data.get('data', {}) or {}

        if not body:
            return Response({
                'success': False,
                'message': 'Notification body is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            from apps.notifications.models import Notification, RecipientType
            from apps.notifications.admin_worker_messages import (
                admin_display_name,
                build_admin_manual_notification,
            )

            admin_name = admin_display_name(request.user)
            custom_title = (request.data.get('title') or '').strip()
            notification_title, notification_message = build_admin_manual_notification(
                admin_name=admin_name,
                body=body,
                extra=data if isinstance(data, dict) else {},
            )
            if custom_title:
                notification_title = (
                    custom_title
                    if custom_title.lower().startswith('from admin')
                    else f'From Admin — {custom_title}'
                )

            notification = Notification.objects.create(
                recipient_type=RecipientType.WORKER,
                recipient_id=worker.worker_id.account_id,
                message=notification_message,
                title=notification_title,
                is_read=False,
            )
            
            logger.info(f'📤 Notification #{notification.notification_id} created for worker {worker.employee_code}')
            
            # FCM push is sent by apps.notifications.signals on Notification.create
            push_sent = bool((getattr(account, 'fcm_token', None) or '').strip())
            
            # ============================================
            # Optional: Send email as fallback
            # ============================================
            email_sent = False
            
            if account and account.email:
                try:
                    send_mail(
                        subject=f'📢 {title}',
                        message=f'{body}\n\n---\nThis notification was sent from the Neat Now admin panel.',
                        from_email='rehanafzal779@gmail.com',
                        recipient_list=[account.email],
                        fail_silently=True,
                    )
                    email_sent = True
                    logger.info(f'📧 Email notification sent to {account.email}')
                except Exception as email_error:
                    logger.warning(f'Email notification failed: {email_error}')
            
            return Response({
                'success': True,
                'message': f'Notification sent to {account.name if account else "worker"}',
                'notification_id': notification.notification_id,
                'email':  account.email if account else None,
                'details': {
                    'stored_in_db': True,
                    'push_sent': push_sent,
                    'email_sent':  email_sent
                }
            }, status=status.HTTP_201_CREATED)
            
        except ImportError:
            # Notification app not installed, fall back to email only
            logger.warning('Notification app not installed, sending email only')
            
            if account and account.email:
                try:
                    send_mail(
                        subject=f'📢 {title}',
                        message=f'{body}\n\n---\nThis notification was sent from the Neat Now admin panel.',
                        from_email='rehanafzal779@gmail.com',
                        recipient_list=[account.email],
                        fail_silently=False,
                    )
                    
                    return Response({
                        'success': True,
                        'message': f'Notification sent via email to {account.email}',
                        'email': account.email
                    })
                except Exception as e:
                    logger.error(f'Failed to send email: {e}')
                    return Response({
                        'success': False,
                        'message': 'Failed to send notification',
                        'error': str(e)
                    }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            else:
                return Response({
                    'success': False,
                    'message': 'Worker has no email and notification system not configured'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e: 
            logger.error(f'❌ Failed to send notification to worker {pk}: {str(e)}')
            return Response({
                'success': False,
                'message': 'Failed to send notification',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # ============================================
    # ✅ SEND EMAIL ENDPOINT
    # ============================================
    @action(detail=True, methods=['post'])
    def send_email(self, request, pk=None):
        """
        Send custom email to worker
        POST /api/workers/{id}/send_email/
        """
        worker = self.get_object()
        account = worker.worker_id
        
        if not account or not account.email:
            return Response({
                'success':  False,
                'message': 'Worker has no email address configured'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        subject = request.data.get('subject', 'Message from Neat Now Admin')
        message = request.data. get('message', '')
        
        if not message:
            return Response({
                'success': False,
                'message': 'Email message content is required'
            }, status=status. HTTP_400_BAD_REQUEST)
        
        try: 
            html_message = f'''
<! DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; background-color: #0f172a; padding: 20px;">
    <div style="max-width:  600px; margin: 0 auto; background:  #1e293b; border-radius: 12px; overflow: hidden;">
        <div style="background: linear-gradient(135deg, #10b981, #14b8a6); padding: 30px; text-align: center;">
            <h1 style="color:  white; margin: 0;">📧 Message from Admin</h1>
        </div>
        <div style="padding: 30px;">
            <p style="color:  #e2e8f0; font-size:  16px;">Hello <strong>{account.name}</strong>,</p>
            <div style="color: #94a3b8; font-size: 14px; line-height:  1.8; white-space: pre-wrap;">{message}</div>
            <hr style="border: none; border-top:  1px solid #334155; margin:  30px 0;">
            <p style="color: #64748b; font-size: 12px; text-align: center;">
                This email was sent from the Neat Now admin panel.
            </p>
        </div>
    </div>
</body>
</html>
            '''
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL or 'rehanafzal779@gmail. com',
                recipient_list=[account. email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger. info(f'✅ Email sent to worker {worker.employee_code} at {account.email}')
            
            return Response({
                'success': True,
                'message':  f'Email sent successfully to {account.email}'
            })
            
        except Exception as e: 
            logger.error(f'❌ Failed to send email to {account.email}: {str(e)}')
            return Response({
                'success':  False,
                'message': 'Failed to send email',
                'error': str(e)
            }, status=status. HTTP_500_INTERNAL_SERVER_ERROR)
    
    # ============================================
    # ✅ GET WORKER ASSIGNMENTS
    # ============================================
    @action(detail=True, methods=['get'])
    def assignments(self, request, pk=None):
        """
        Get worker's current assignments
        GET /api/workers/{id}/assignments/
        """
        worker = self.get_object()
        
        try:
            from apps.reports.models import Report
            from apps.reports.serializers import resolve_report_location_display
            
            # Worker profile "Current Assignments" should show tasks the worker is
            # actively working on right now.
            assignments = Report.objects.filter(
                worker_id=worker,
                status='In Progress'
            ).order_by('-started_at', '-submitted_at')
            
            data = []
            for report in assignments:
                rid = getattr(report, 'report_id', None)
                stored = (getattr(report, 'location_address', None) or '').strip()
                # Same string as ReportListSerializer `location` (citizen address, else geocode).
                readable_location = resolve_report_location_display(report)
                data.append({
                    'id': str(rid) if rid is not None else '',
                    'report_id': rid,
                    # Raw DB field (citizen UI text); mirrors worker app / reports API.
                    'location_address': stored or None,
                    # Return human-readable address (not raw GPS coordinates)
                    'location': readable_location or 'Unknown Location',
                    'address': readable_location or 'Unknown Location',
                    'status': report.status,
                    # Mirrors reports serializer rule used elsewhere in admin panel.
                    'reported_by': (
                        'Assigned by Admin'
                        if report.accepted_at is None and report.worker_id is not None
                        else (
                            f'Reported by {report.citizen_id.name}'
                            if getattr(report, 'citizen_id', None)
                            else 'Reported by Citizen'
                        )
                    ),
                    'waste_type': report.waste_type if hasattr(report, 'waste_type') else 'General',
                    'category': report.category if hasattr(report, 'category') else '',
                    'priority': getattr(report, 'priority', None) or 'normal',
                    'created_at': report.submitted_at.isoformat() if report.submitted_at else None,
                    'assigned_at': (
                        report.started_at.isoformat()
                        if getattr(report, 'started_at', None)
                        else (
                            report.accepted_at.isoformat()
                            if getattr(report, 'accepted_at', None)
                            else None
                        )
                    ),
                    'due_date': report.due_date.isoformat() if hasattr(report, 'due_date') and report.due_date else None,
                })
            
            return Response({
                'success': True,
                'count': len(data),
                'data': data
            })
            
        except ImportError:
            logger.warning('Report model not available')
            return Response({
                'success':  True,
                'count': 0,
                'data': []
            })
        except Exception as e: 
            logger.error(f'Error fetching assignments: {str(e)}')
            return Response({
                'success': True,
                'count': 0,
                'data': []
            })
    
    # ============================================
    # ✅ GET WORKER ACTIVITY LOG
    # ============================================
    @action(detail=True, methods=['get'])
    def activity(self, request, pk=None):
        """
        Get worker's activity log
        GET /api/workers/{id}/activity/
        """
        worker = self.get_object()
        limit = int(request.query_params.get('limit', 50))
        
        try:
            # Try to get from ActivityLog model if it exists
            from apps.core.models import ActivityLog
            
            activities = ActivityLog.objects.filter(
                user=worker.worker_id
            ).order_by('-created_at')[:limit]
            
            data = [{
                'id':  str(log.id),
                'action': log.action,
                'description': log.description if hasattr(log, 'description') else log.action,
                'timestamp': log.created_at.isoformat(),
                'created_at': log.created_at.isoformat(),
                'report_id': str(log.report_id) if hasattr(log, 'report_id') and log.report_id else None,
            } for log in activities]
            
            return Response({
                'success': True,
                'count':  len(data),
                'data': data
            })
            
        except ImportError:
            # Do not synthesize timeline from report history.
            # Pending/in-progress/resolved cards are shown in dedicated UI sections.
            return Response({
                'success': True,
                'count': 0,
                'data': []
            })
        
        except Exception as e:
            logger.error(f'Error fetching activity log: {str(e)}')
        
        # Return empty if nothing works
        return Response({
            'success':  True,
            'count': 0,
            'data':  []
        })
    
    # ============================================
    # EXISTING ENDPOINTS
    # ============================================
    
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload_photo(self, request, pk=None):
        """✅ DEDICATED ENDPOINT FOR PHOTO UPLOAD"""
        worker = self.get_object()
        
        if 'photo' not in request.FILES: 
            return Response({
                'success': False,
                'message': 'No photo provided'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        photo = request.FILES['photo']
        
        if worker.worker_id. profile_photo: 
            worker.worker_id.profile_photo.delete(save=False)
        
        worker. worker_id.profile_photo = photo
        worker.worker_id.save()
        
        return Response({
            'success': True,
            'message': 'Photo uploaded successfully',
            'photo_url': request.build_absolute_uri(worker.worker_id. profile_photo.url) if worker.worker_id.profile_photo else None
        })
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle worker account active/inactive (login access)."""
        worker = self.get_object()
        worker.worker_id.is_active = not worker.worker_id.is_active
        worker.worker_id.save(update_fields=['is_active'])

        # If deactivated, terminate all active sessions immediately.
        if not worker.worker_id.is_active:
            try:
                from apps.accounts.models import UserSession
                sessions = UserSession.objects.filter(
                    account=worker.worker_id,
                    is_active=True
                )
                for s in sessions:
                    s.terminate()
            except Exception:
                # Session termination should not break toggle.
                pass

        return Response({
            'success': True,
            'message': f'Worker status changed to {"active" if worker.worker_id.is_active else "inactive"}',
            'is_active': worker.worker_id.is_active
        })
    
    @action(detail=True, methods=['post'])
    def start_tracking(self, request, pk=None):
        """Start GPS tracking for worker"""
        worker = self. get_object()
        worker.is_tracking = True
        worker.save()
        
        return Response({
            'success': True,
            'message': 'Tracking started',
            'is_tracking': True
        })
    
    @action(detail=True, methods=['post'])
    def stop_tracking(self, request, pk=None):
        """Stop GPS tracking for worker"""
        worker = self.get_object()
        worker.is_tracking = False
        worker.save()
        
        return Response({
            'success': True,
            'message':  'Tracking stopped',
            'is_tracking': False
        })

    @action(detail=True, methods=['post'], url_path='force_inactive')
    def force_inactive(self, request, pk=None):
        """
        Admin-only: force worker offline when they forgot to log out.

        Mirrors worker logout for online/tracking (is_tracking=False + session end).
        Does NOT change Account.is_active — use toggle_active for login access.
        Admin cannot force Active; worker must log in again.
        """
        worker = self.get_object()
        account = worker.worker_id

        if not worker.is_tracking:
            return Response({
                'success': True,
                'message': 'Worker is already inactive',
                'is_tracking': False,
            })

        worker.is_tracking = False
        worker.save(update_fields=['is_tracking'])

        terminated_count = 0
        try:
            from apps.accounts.models import UserSession
            sessions = UserSession.objects.filter(
                account=account,
                is_active=True,
            )
            for session in sessions:
                session.terminate()
                terminated_count += 1
        except Exception:
            pass

        logger.info(
            'Admin forced worker inactive: worker_id=%s account=%s sessions=%s',
            worker.pk,
            account.email,
            terminated_count,
        )

        return Response({
            'success': True,
            'message': (
                'Worker marked inactive and signed out. '
                'They must log in again to become active.'
            ),
            'is_tracking': False,
            'sessions_terminated': terminated_count,
        })
    
    @action(detail=True, methods=['get'])
    def reports(self, request, pk=None):
        """Get worker's assigned reports"""
        worker = self.get_object()
        
        from apps.reports.models import Report
        from apps.reports.serializers import ReportListSerializer
        
        reports = Report.objects. filter(worker_id=worker)
        
        status_filter = request. query_params.get('status')
        if status_filter: 
            reports = reports.filter(status=status_filter)
        
        serializer = ReportListSerializer(reports, many=True)
        
        return Response({
            'success': True,
            'count': reports.count(),
            'data':  serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get worker statistics"""
        worker = self.get_object()
        
        from apps.reports.models import Report
        from apps.feedback.models import Feedback
        from django.db.models import Avg
        from django.utils import timezone
        from datetime import timedelta
        
        days = int(request.query_params.get('days', 30))
        start_date = timezone. now() - timedelta(days=days)
        
        reports = Report.objects. filter(
            worker_id=worker, 
            resolved_at__gte=start_date, 
            status='Resolved'
        )
        all_reports = Report.objects.filter(worker_id=worker)

        # Rating lives on Feedback (OneToOne with Report), not on Report.
        avg_rating_period = Feedback.objects.filter(
            report_id__in=reports
        ).aggregate(avg=Avg('rating'))['avg'] or 0

        # Avg resolution time for resolved reports (accepted -> resolved), in hours.
        avg_resolution_time_hours = 0.0
        timed_reports = all_reports.filter(
            status='Resolved',
            accepted_at__isnull=False,
            resolved_at__isnull=False
        )
        if timed_reports.exists():
            total_hours = 0.0
            count = 0
            for rep in timed_reports:
                time_diff = rep.resolved_at - rep.accepted_at
                total_hours += (time_diff.total_seconds() / 3600.0)
                count += 1
            if count > 0:
                avg_resolution_time_hours = total_hours / count

        total_reports = all_reports.count()
        done_reports = all_reports.filter(status='Resolved').count()
        in_progress_reports = all_reports.filter(status='In Progress').count()
        resolution_rate = round((done_reports / total_reports * 100) if total_reports > 0 else 0, 2)
        
        performance = {
            'total_resolved': reports.count(),
            'avg_rating': float(avg_rating_period),
            'period_days': days,
            'avg_resolution_time_hours': round(avg_resolution_time_hours, 2),
            'done_reports': done_reports,
            'in_progress_reports': in_progress_reports,
            'resolution_rate': resolution_rate,
        }
        
        current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly_stat = WorkerMonthlyStats.objects.filter(
            worker_id=worker,
            month=current_month.date()
        ).first()
        
        monthly = {
            'resolved_tasks': monthly_stat.resolved_tasks if monthly_stat else 0,
            'avg_rating': float(monthly_stat. avg_rating) if monthly_stat else 0,
            'badge':  monthly_stat.badge if monthly_stat else 'None',
            'monthly_rank': monthly_stat. monthly_rank if monthly_stat else None
        }
        
        lifetime = {
            'total_tasks': worker.total_tasks,
            'avg_rating': float(worker.avg_rating),
            'employee_code': worker.employee_code
        }
        
        return Response({
            'success': True,
            'data': {
                'performance': performance,
                'monthly': monthly,
                'lifetime': lifetime
            }
        })
    
    @action(detail=True, methods=['get'])
    def location_history(self, request, pk=None):
        """Get worker's location history"""
        worker = self.get_object()
        
        hours = int(request. query_params.get('hours', 24))
        
        from django.utils import timezone
        from datetime import timedelta
        
        start_time = timezone.now() - timedelta(hours=hours)
        locations = WorkerLocation.objects.filter(
            worker_id=worker,
            recorded_at__gte=start_time
        ).order_by('-recorded_at')
        
        serializer = WorkerLocationSerializer(locations, many=True)
        
        return Response({
            'success': True,
            'count': locations.count(),
            'data': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def top_performers(self, request):
        """Get top performing workers"""
        limit = int(request. query_params.get('limit', 10))
        
        workers = Worker.objects. select_related('worker_id').filter(
            worker_id__is_active=True
        ).order_by('-avg_rating', '-total_tasks')[:limit]
        
        serializer = WorkerListSerializer(workers, many=True)
        
        return Response({
            'success': True,
            'count': workers.count(),
            'results': serializer.data
        })
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        """Get workers with low workload"""
        max_tasks = int(request.query_params.get('max_tasks', 3))
        
        from apps.reports.models import Report
        
        workers = Worker. objects.select_related('worker_id').filter(
            worker_id__is_active=True
        ).annotate(
            active_tasks=Count(
                'assigned_reports', 
                filter=Q(assigned_reports__status__in=['Assigned', 'In Progress'])
            )
        ).filter(
            active_tasks__lte=max_tasks
        ).order_by('active_tasks', '-avg_rating')
        
        serializer = WorkerListSerializer(workers, many=True)
        
        return Response({
            'success': True,
            'count': workers.count(),
            'results':  serializer.data
        })


# ==================== WORKER RANKINGS API ====================

class WorkerTrackingStatusView(APIView):
    """
    Worker self-service endpoint.

    GET  /api/workers/tracking/ — current is_tracking (mobile poll after admin force inactive)
    POST /api/workers/tracking/ — set online/offline (login/logout)
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        try:
            worker = Worker.objects.get(worker_id=request.user)
        except Worker.DoesNotExist:
            return Response(
                {'success': False, 'error': 'Worker profile not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response(
            {'success': True, 'is_tracking': worker.is_tracking},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        try:
            # Resolve worker from authenticated account
            user = request.user
            worker = Worker.objects.get(worker_id=user)
        except Worker.DoesNotExist:
            return Response(
                {'success': False, 'error': 'Worker profile not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        raw = request.data.get('is_tracking', request.data.get('tracking'))
        if raw is None:
            return Response(
                {'success': False, 'error': '`is_tracking` is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        is_tracking = bool(raw) if isinstance(raw, bool) else str(raw).lower() in [
            'true',
            '1',
            'yes',
            'on',
        ]

        worker.is_tracking = is_tracking
        worker.save(update_fields=['is_tracking'])

        # Optional: record a location snapshot if coordinates were provided.
        lat = request.data.get('latitude', request.data.get('lat'))
        lng = request.data.get('longitude', request.data.get('lng', request.data.get('lon')))
        if lat is not None and lng is not None:
            try:
                WorkerLocation.objects.create(
                    worker_id=worker,
                    latitude=Decimal(str(lat)),
                    longitude=Decimal(str(lng)),
                )
            except Exception:
                # Location snapshot failure shouldn't block tracking state update.
                pass

        return Response(
            {'success': True, 'is_tracking': worker.is_tracking},
            status=status.HTTP_200_OK,
        )

class WorkerRankingsView(APIView):
    """
    GET /api/workers/rankings/
    Get real-time worker rankings/leaderboard based on resolved reports.
    Accessible by authenticated workers
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    @staticmethod
    def _badge_from_percentile(percentile):
        """
        Badge by rank percentile so higher-report workers get better badges.
        Percentile is rank/total in [0,1].
        """
        if percentile <= 0.10:
            return 'Diamond'
        if percentile <= 0.30:
            return 'Gold'
        if percentile <= 0.60:
            return 'Silver'
        return 'Bronze'

    def get(self, request):
        """Get real-time worker rankings using lifetime resolved reports."""
        try:
            limit = int(request.query_params.get('limit', 50))
            rankings_data = calculate_rankings_snapshot(request=request)
            try:
                sync_badge_history_from_rankings(rankings_data)
            except Exception as sync_err:
                logger.warning(
                    'Badge history sync failed (leaderboard data still returned): %s',
                    sync_err,
                    exc_info=True,
                )

            full_rankings = rankings_data

            current_worker_info = None
            current_worker_rank = None
            try:
                user = request.user
                worker = Worker.objects.get(worker_id=user)
                for entry in full_rankings:
                    if str(entry.get('worker_id')) == str(worker.worker_id.account_id):
                        current_worker_rank = entry.get('rank')
                        current_worker_info = {
                            'worker_id': entry.get('worker_id'),
                            'employee_code': entry.get('employee_code'),
                            'name': entry.get('name'),
                            'profile_image': entry.get('profile_image'),
                            'points': entry.get('points'),
                            'resolved_tasks': entry.get('resolved_tasks'),
                            'avg_rating': entry.get('avg_rating'),
                            'badge': entry.get('badge'),
                            'rank': entry.get('rank'),
                        }
                        break
            except Worker.DoesNotExist:
                current_worker_info = None
            except Exception as e:
                logger.warning(f"Could not get current worker info: {e}")

            if limit > 0:
                to_respond = full_rankings[:limit]
            else:
                to_respond = full_rankings

            return Response({
                'success': True,
                'count': len(to_respond),
                'current_worker': _coerce_json_value(current_worker_info)
                if current_worker_info
                else None,
                'current_worker_rank': _coerce_json_value(current_worker_rank),
                'data': _rankings_json_safe(to_respond),
            })
            
        except Exception as e:
            logger.error(f"Error fetching worker rankings: {e}")
            return Response({
                'success': False,
                'message': 'Error fetching rankings',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerStatsView(APIView):
    """
    GET /api/workers/stats/
    Get worker statistics (pending, done, average time)
    Accessible by authenticated workers
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def get(self, request):
        """Get worker stats: pending, done, average resolution time"""
        try:
            user = request.user
            
            # Get worker from authenticated user
            try:
                worker = Worker.objects.get(worker_id=user)
            except Worker.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Only workers can view their stats'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Import Report model
            from apps.reports.models import Report
            from django.db.models import Avg, Count, Q
            from datetime import timedelta
            
            # Get all reports assigned to this worker
            worker_reports = Report.objects.filter(worker_id=worker)
            
            # Calculate pending reports (status = 'Pending' or 'Assigned')
            pending_count = worker_reports.filter(
                Q(status='Pending') | Q(status='Assigned')
            ).count()
            
            # Calculate done/resolved reports
            done_count = worker_reports.filter(status='Resolved').count()
            
            # Calculate average resolution time (in hours)
            # Time from accepted_at to resolved_at for resolved reports
            resolved_reports = worker_reports.filter(
                status='Resolved',
                accepted_at__isnull=False,
                resolved_at__isnull=False
            )
            
            avg_resolution_time_hours = 0.0
            if resolved_reports.exists():
                # Calculate time difference for each resolved report
                time_differences = []
                for report in resolved_reports:
                    if report.accepted_at and report.resolved_at:
                        time_diff = report.resolved_at - report.accepted_at
                        time_diff_hours = time_diff.total_seconds() / 3600.0
                        time_differences.append(time_diff_hours)
                
                if time_differences:
                    avg_resolution_time_hours = sum(time_differences) / len(time_differences)
            
            # Format average time (show hours and minutes)
            avg_hours = int(avg_resolution_time_hours)
            avg_minutes = int((avg_resolution_time_hours - avg_hours) * 60)
            
            # Total reports assigned to this worker
            total_reports = worker_reports.count()
            
            # In progress reports
            in_progress_count = worker_reports.filter(status='In Progress').count()
            
            return Response({
                'success': True,
                'data': {
                    'total_reports': total_reports,
                    'pending_reports': pending_count,
                    'done_reports': done_count,  # Resolved reports
                    'in_progress_reports': in_progress_count,
                    'avg_resolution_time_hours': round(avg_resolution_time_hours, 2),
                    'avg_resolution_time_formatted': f'{avg_hours}h {avg_minutes}m' if avg_hours > 0 or avg_minutes > 0 else '0h 0m',
                    'resolution_rate': round((done_count / total_reports * 100) if total_reports > 0 else 0, 2),
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error fetching worker stats: {e}")
            return Response({
                'success': False,
                'message': 'Error fetching stats',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerAnalyticsView(APIView):
    """
    GET /api/workers/analytics/
    Get comprehensive analytics data for worker (Total, Done, Rate, Time, graphs, etc.)
    Accessible by authenticated workers
    """
    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]
    
    def get(self, request):
        """Get worker analytics: metrics, weekly data, daily activity, waste distribution, top locations"""
        try:
            user = request.user
            
            # Get worker from authenticated user
            try:
                worker = Worker.objects.get(worker_id=user)
            except Worker.DoesNotExist:
                return Response({
                    'success': False,
                    'message': 'Only workers can view their analytics'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Import Report model
            from apps.reports.models import Report
            from django.db.models import Count, Q
            from datetime import timedelta
            from collections import defaultdict
            
            # Get period parameter (week, month, year) - default to month
            period = request.query_params.get('period', 'month')
            
            # Calculate date range based on period
            now = timezone.now()
            if period == 'week':
                start_date = now - timedelta(days=7)
            elif period == 'year':
                start_date = now - timedelta(days=365)
            else:  # month (default)
                start_date = now - timedelta(days=30)
            
            # Get all reports assigned to this worker
            worker_reports = Report.objects.filter(worker_id=worker)
            
            # Filter by period
            period_reports = worker_reports.filter(submitted_at__gte=start_date)
            
            # ==================== METRICS ====================
            total_tasks = period_reports.count()
            done_tasks = period_reports.filter(status='Resolved').count()
            pending_tasks = period_reports.filter(Q(status='Pending') | Q(status='Assigned')).count()
            in_progress_tasks = period_reports.filter(status='In Progress').count()
            
            # Calculate completion rate (Done / Total * 100)
            completion_rate = round((done_tasks / total_tasks * 100) if total_tasks > 0 else 0, 2)
            
            # Calculate average resolution time (in hours)
            resolved_reports = worker_reports.filter(
                status='Resolved',
                accepted_at__isnull=False,
                resolved_at__isnull=False
            )
            
            avg_resolution_time_hours = 0.0
            if resolved_reports.exists():
                time_differences = []
                for report in resolved_reports:
                    if report.accepted_at and report.resolved_at:
                        time_diff = report.resolved_at - report.accepted_at
                        time_diff_hours = time_diff.total_seconds() / 3600.0
                        time_differences.append(time_diff_hours)
                
                if time_differences:
                    avg_resolution_time_hours = sum(time_differences) / len(time_differences)
            
            # Format average time (in minutes for display)
            avg_resolution_time_minutes = int(avg_resolution_time_hours * 60)
            
            # ==================== WEEKLY DATA (Last 7 days) ====================
            weekly_data = []
            for i in range(7):
                date = (now - timedelta(days=6-i)).date()
                day_count = period_reports.filter(
                    submitted_at__date=date
                ).count()
                weekly_data.append(day_count)
            
            # ==================== DAILY ACTIVITY (Last 7 days) ====================
            daily_resolved = []
            daily_reported = []
            for i in range(7):
                date = (now - timedelta(days=6-i)).date()
                resolved_count = period_reports.filter(
                    status='Resolved',
                    resolved_at__date=date
                ).count()
                reported_count = period_reports.filter(
                    submitted_at__date=date
                ).count()
                daily_resolved.append(resolved_count)
                daily_reported.append(reported_count)
            
            # ==================== WASTE DISTRIBUTION ====================
            waste_distribution = {}
            waste_types = period_reports.values('waste_type').annotate(
                count=Count('report_id')
            )
            for item in waste_types:
                waste_type = item['waste_type'] or 'Other'
                waste_distribution[waste_type] = item['count']
            
            # Map to standard categories
            plastic_tasks = waste_distribution.get('Plastic', 0) + waste_distribution.get('Plastic Waste', 0)
            organic_tasks = waste_distribution.get('Organic', 0) + waste_distribution.get('Organic Waste', 0)
            electronic_tasks = waste_distribution.get('Electronic', 0) + waste_distribution.get('Electronic Waste', 0)
            hazardous_tasks = waste_distribution.get('Hazardous', 0) + waste_distribution.get('Hazardous Waste', 0)
            other_tasks = total_tasks - (plastic_tasks + organic_tasks + electronic_tasks + hazardous_tasks)
            
            # ==================== TOP LOCATIONS ====================
            # Get top locations by report count (group by rounded coordinates)
            top_locations_data = []
            location_groups = defaultdict(int)
            location_coords = {}  # Store coordinates for each location group
            location_samples = {}  # Store a sample report for each location (for geocoding)
            
            # Group reports by rounded coordinates (to cluster nearby reports)
            for report in period_reports:
                if report.latitude and report.longitude:
                    # Round to 3 decimal places (~100m precision) for grouping
                    lat_key = round(float(report.latitude), 3)
                    lng_key = round(float(report.longitude), 3)
                    location_key = f"{lat_key},{lng_key}"
                    location_groups[location_key] += 1
                    if location_key not in location_coords:
                        location_coords[location_key] = {
                            'latitude': float(report.latitude),
                            'longitude': float(report.longitude),
                        }
                        location_samples[location_key] = report  # Store sample for geocoding
            
            # Sort and get top 5
            sorted_locations = sorted(location_groups.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # ✅ Import geocoding function
            from apps.reports.serializers import get_location_from_coordinates
            
            for idx, (loc_key, count) in enumerate(sorted_locations, start=1):
                lat, lng = loc_key.split(',')
                coords = location_coords.get(loc_key, {})
                sample_report = location_samples.get(loc_key)
                
                # ✅ Get location name using geocoding
                location_name = f'Location {idx}'
                if sample_report and sample_report.latitude and sample_report.longitude:
                    try:
                        geocoded_name = get_location_from_coordinates(
                            float(sample_report.latitude),
                            float(sample_report.longitude)
                        )
                        if geocoded_name and geocoded_name != 'Unknown Location':
                            # Use first part of address (e.g., "D Ground" from "D Ground, Civil Lines...")
                            location_parts = geocoded_name.split(',')
                            location_name = location_parts[0].strip() if location_parts else geocoded_name
                            # Truncate if too long
                            if len(location_name) > 30:
                                location_name = location_name[:27] + '...'
                    except Exception as e:
                        logger.warning(f"Geocoding error for {loc_key}: {e}")
                        location_name = f'Location {idx}'
                
                top_locations_data.append({
                    'name': location_name,  # ✅ Use geocoded name
                    'reports': count,  # ✅ Use 'reports' instead of 'count'
                    'count': count,  # Keep for backward compatibility
                    'latitude': coords.get('latitude', float(lat)),
                    'longitude': coords.get('longitude', float(lng)),
                })
            
            # ==================== REPORTS OVER TIME (For graphs) ====================
            # Generate data for the selected period
            if period == 'week':
                labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
                data_points = weekly_data
            elif period == 'year':
                # Monthly data for year
                labels = []
                data_points = []
                for i in range(12):
                    month_start = now.replace(day=1) - timedelta(days=30 * (11-i))
                    month_end = month_start + timedelta(days=30)
                    month_count = period_reports.filter(
                        submitted_at__gte=month_start,
                        submitted_at__lt=month_end
                    ).count()
                    labels.append(month_start.strftime('%b'))
                    data_points.append(month_count)
            else:  # month
                # Weekly data for month (4 weeks)
                labels = ['Week 1', 'Week 2', 'Week 3', 'Week 4']
                data_points = []
                for i in range(4):
                    week_start = start_date + timedelta(days=7*i)
                    week_end = week_start + timedelta(days=7)
                    week_count = period_reports.filter(
                        submitted_at__gte=week_start,
                        submitted_at__lt=week_end
                    ).count()
                    data_points.append(week_count)
            
            # ==================== PERFORMANCE METRICS ====================
            # Calculate efficiency score (based on completion rate and average time)
            efficiency_score = int(completion_rate * 0.7 + (100 - min(avg_resolution_time_hours * 10, 100)) * 0.3)
            efficiency_score = max(0, min(100, efficiency_score))  # Clamp between 0-100
            
            # Get worker rating
            worker_rating = float(worker.avg_rating) if worker.avg_rating else 4.5
            
            # Calculate growth rate (compare with previous period)
            previous_start = start_date - (now - start_date)
            previous_period_reports = worker_reports.filter(
                submitted_at__gte=previous_start,
                submitted_at__lt=start_date
            )
            previous_done = previous_period_reports.filter(status='Resolved').count()
            
            growth_rate = 0.0
            if previous_done > 0:
                growth_rate = round(((done_tasks - previous_done) / previous_done * 100), 2)
            
            return Response({
                'success': True,
                'data': {
                    # Metrics (for 4 cards)
                    'total_reports': total_tasks,
                    'resolved_reports': done_tasks,
                    'pending_reports': pending_tasks,
                    'in_progress_reports': in_progress_tasks,
                    'completion_rate': completion_rate,  # Rate percentage
                    'avg_resolution_time_hours': round(avg_resolution_time_hours, 2),
                    'avg_resolution_time_minutes': avg_resolution_time_minutes,  # For display
                    
                    # Performance metrics
                    'performance_metrics': {
                        'efficiency_score': efficiency_score,
                        'response_time_avg': avg_resolution_time_minutes,
                        'customer_satisfaction': worker_rating,
                    },
                    
                    # Weekly data (for performance chart)
                    'weekly_data': weekly_data,
                    
                    # Daily activity (for weekly activity chart)
                    'daily_activity': {
                        'resolved': daily_resolved,
                        'reported': daily_reported,
                    },
                    
                    # Waste distribution
                    'waste_distribution': {
                        'Plastic Waste': plastic_tasks,
                        'Organic Waste': organic_tasks,
                        'Electronic Waste': electronic_tasks,
                        'Hazardous Waste': hazardous_tasks,
                        'Mixed Waste': other_tasks,
                    },
                    
                    # Task breakdown by type
                    'plastic_tasks': plastic_tasks,
                    'organic_tasks': organic_tasks,
                    'electronic_tasks': electronic_tasks,
                    'hazardous_tasks': hazardous_tasks,
                    'other_tasks': other_tasks,
                    
                    # Reports over time (for graphs)
                    'reports_over_time': {
                        'labels': labels,
                        'data': data_points,
                    },
                    
                    # Top locations
                    'top_locations': top_locations_data,
                    
                    # Additional metrics
                    'efficiency': efficiency_score,
                    'user_rating': worker_rating,
                    'growth_rate': growth_rate,
                    'resolution_rate': completion_rate,
                }
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error fetching worker analytics: {e}")
            import traceback
            traceback.print_exc()
            return Response({
                'success': False,
                'message': 'Error fetching analytics',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WorkerProfileSummaryView(APIView):
    """
    GET /api/workers/profile-summary/
    Returns worker profile header + stats payload for employee profile UI.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        try:
            # Keep badge transitions updated before serving profile.
            snapshot = calculate_rankings_snapshot(request=None)
            sync_badge_history_from_rankings(snapshot)

            worker = get_worker_for_user(request.user)
            if not worker:
                return Response(
                    {
                        "success": False,
                        "message": "Only workers can access profile summary",
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

            payload = build_profile_summary_payload(worker, request)
            return Response({"success": True, "data": payload}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching worker profile summary: {e}")
            return Response(
                {
                    "success": False,
                    "message": "Error fetching worker profile summary",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class WorkerBadgeHistoryView(APIView):
    """
    GET /api/workers/badge-history/
    Returns worker badge history with start/end date ranges.
    """

    permission_classes = [IsAuthenticated]
    authentication_classes = [JWTAuthentication]

    def get(self, request):
        try:
            # Sync first so history reflects latest leaderboard changes.
            snapshot = calculate_rankings_snapshot(request=None)
            sync_badge_history_from_rankings(snapshot)

            worker = get_worker_for_user(request.user)
            if not worker:
                return Response(
                    {"success": False, "message": "Only workers can access badge history"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            rows = worker.badge_history.all().order_by("-started_at")
            data = [
                {
                    "id": row.history_id,
                    "badge": row.badge,
                    "started_at": row.started_at.isoformat(),
                    "ended_at": row.ended_at.isoformat() if row.ended_at else None,
                    "is_current": row.is_current,
                }
                for row in rows
            ]
            return Response({"success": True, "data": data}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error fetching worker badge history: {e}")
            return Response(
                {
                    "success": False,
                    "message": "Error fetching badge history",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )