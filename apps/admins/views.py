from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework. response import Response
from rest_framework. permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework import exceptions
from django.utils import timezone
from django.db.models import Q, Count, Avg
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth. tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth import authenticate, get_user_model
from datetime import timedelta
from rest_framework_simplejwt. tokens import RefreshToken

from . models import Admin
from .serializers import (
    AdminSerializer,
    AdminCreateSerializer,
    AdminUpdateSerializer,
    AdminLoginSerializer,
    AdminPasswordChangeSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer
)
from .permissions import IsAdmin, IsSuperAdmin
from .authentication import AdminJWTAuthentication

import logging

logger = logging.getLogger(__name__)

User = get_user_model()

# ==================== LOGIN ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def admin_login(request):
    """
    Admin login endpoint
    POST /api/admins/login/
    """
    email = request.data.get('email')
    password = request.data. get('password')
    
    if not email or not password: 
        return Response({
            'success': False,
            'error': 'Email and password are required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    logger.info(f'🔐 Admin login attempt:  {email}')
    
    try:
        # ✅ Get Admin directly (not User)
        admin = Admin.objects.get(email=email)
        
        # Check if active
        if not admin.is_active:
            logger.error(f'❌ Inactive admin: {email}')
            return Response({
                'success': False,
                'error':  'Account is disabled'
            }, status=status. HTTP_403_FORBIDDEN)
        
        # Check password
        if not admin.check_password(password):
            logger. error(f'❌ Invalid password for:  {email}')
            return Response({
                'success': False,
                'error': 'Invalid credentials'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # ✅ Generate tokens for Admin
        refresh = RefreshToken()
        
        # Add custom claims
        refresh['admin_id'] = admin.admin_id
        refresh['email'] = admin.email
        refresh['user_type'] = 'admin'
        refresh['role'] = admin.role
        refresh['name'] = admin.name
        
        # Update last login
        admin.update_last_login()
        
        logger.info(f'✅ Admin logged in successfully: {email}')
        
        return Response({
            'success': True,
            'message': 'Login successful',
            'data': {
                'access':  str(refresh. access_token),
                'refresh': str(refresh),
                'user':  AdminSerializer(admin).data
            }
        }, status=status.HTTP_200_OK)
        
    except Admin.DoesNotExist:
        logger.error(f'❌ Admin not found: {email}')
        return Response({
            'success': False,
            'error': 'Invalid credentials'
        }, status=status.HTTP_401_UNAUTHORIZED)
    except Exception as e: 
        logger.error(f'❌ Login error: {str(e)}', exc_info=True)
        return Response({
            'success':  False,
            'error': 'Login failed'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
# ==================== PROFILE ====================
class AdminProfileView(APIView):
    """GET /api/admins/profile/ - Get current admin profile"""
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated, IsAdmin]
    
    def get(self, request):
        user = request.user  # Already Admin instance
        
        serializer = AdminSerializer(user)
        return Response({
            'success': True,
            'data': serializer.data
        })
    
    def put(self, request):
        """Update admin profile"""
        user = request.user  # Already Admin instance
        
        serializer = AdminUpdateSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({
                'success': True,
                'message': 'Profile updated successfully',
                'data': AdminSerializer(user).data
            })
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)

# ==================== PASSWORD CHANGE ====================

class AdminPasswordChangeView(APIView):
    """POST /api/admins/password-change/ - Change admin password"""
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated, IsAdmin]
    
    def post(self, request):
        serializer = AdminPasswordChangeSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user = request.user
        
        # Check old password
        if not user.check_password(serializer. validated_data['old_password']):
            return Response({
                'success': False,
                'message': 'Current password is incorrect'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set new password
        user.set_password(serializer.validated_data['new_password'])
        user.save()
        
        # Send confirmation email
        try:
            self.send_password_change_email(user)
        except Exception as e:
            logger. error(f'Failed to send password change email: {e}')
        
        logger.info(f'✅ Password changed for: {user.email}')
        
        return Response({
            'success': True,
            'message': 'Password changed successfully.  Please login again with your new password.'
        })
    
    def send_password_change_email(self, user):
        """Send password change confirmation email"""
        admin_panel_url = f"{settings. FRONTEND_URL}/admin/login"
        
        subject = '🔐 Admin Password Changed Successfully'
        
        html_message = f"""
        <! DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                . container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #673AB7; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 30px; background-color: #f9f9f9; }}
                .button {{ 
                    display: inline-block; 
                    padding: 14px 28px; 
                    background-color: #673AB7; 
                    color: white ! important; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin:  20px 0;
                    font-weight: bold;
                }}
                .alert {{ 
                    background-color: #f8d7da; 
                    border-left: 4px solid #dc3545; 
                    padding: 12px; 
                    margin: 20px 0;
                }}
                .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 Password Changed</h1>
                </div>
                <div class="content">
                    <p>Hello {user.get_full_name() or user.email},</p>
                    <p>Your admin account password has been changed successfully.</p>
                    
                    <div class="alert">
                        <strong>⚠️ Security Alert:</strong> If you did not make this change, 
                        please contact the system administrator immediately.
                    </div>
                    
                    <p style="text-align: center;">
                        <a href="{admin_panel_url}" class="button">Go to Admin Panel</a>
                    </p>
                </div>
                <div class="footer">
                    <p>This is an automated message, please do not reply.</p>
                    <p>&copy; 2024 Neat Now. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_mail(
            subject=subject,
            message=f'Your password was changed.  If this wasn\'t you, contact support immediately.',
            from_email='afzalrehan779@gmail.com',
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=True,
        )


# ==================== PASSWORD RESET REQUEST ====================

class PasswordResetRequestView(APIView):
    """POST /api/admins/password-reset/request/ - Request password reset"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data['email']
        
        try:
            user = User.objects.get(email=email)
            
            # Check if user is admin
            is_admin = (
                hasattr(user, 'admin_id') or 
                user.is_staff or 
                user.is_superuser
            )
            
            if not is_admin:
                logger.warning(f'Password reset requested for non-admin: {email}')
                return Response({
                    'success': True,
                    'message': 'If an admin account exists, a reset link has been sent'
                })
            
            if not user.is_active:
                return Response({
                    'success':  False,
                    'message': 'This account is disabled'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Generate token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Send reset email
            self.send_password_reset_email(user, token, uid)
            
            logger.info(f'Password reset requested for: {email}')
            
            return Response({
                'success': True,
                'message': 'Password reset link sent to your email'
            })
            
        except User.DoesNotExist:
            logger.warning(f'Password reset attempted for non-existent email: {email}')
            # Don't reveal if email exists (security)
            return Response({
                'success': True,
                'message': 'If an admin account exists, a reset link has been sent'
            })
        except Exception as e:
            logger.error(f'Password reset error: {e}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to process password reset'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def send_password_reset_email(self, user, token, uid):
        """Send password reset email"""
        reset_url = f"{settings. FRONTEND_URL}/admin/reset-password? uid={uid}&token={token}"
        
        subject = '🔐 Admin Password Reset Request'
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family:  Arial, sans-serif; line-height: 1.6; color: #333; }}
                . container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #673AB7; color:  white; padding: 20px; text-align: center; }}
                .content {{ padding: 30px; background-color: #f9f9f9; }}
                .button {{ 
                    display: inline-block; 
                    padding: 14px 28px; 
                    background-color: #673AB7; 
                    color: white ! important; 
                    text-decoration: none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .warning {{ 
                    background-color: #fff3cd; 
                    border-left: 4px solid #ffc107; 
                    padding: 12px; 
                    margin: 20px 0;
                }}
                .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
                .link {{ color: #673AB7; word-break: break-all; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔐 Password Reset</h1>
                </div>
                <div class="content">
                    <p>Hello {user.get_full_name() or user.email},</p>
                    <p>Click the button below to reset your password:</p>
                    
                    <p style="text-align: center;">
                        <a href="{reset_url}" class="button">Reset Password</a>
                    </p>
                    
                    <p>Or copy this link: </p>
                    <p class="link">{reset_url}</p>
                    
                    <div class="warning">
                        <strong>⚠️ Important:</strong> This link expires in 1 hour.
                        If you didn't request this, please ignore this email.
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated message, please do not reply.</p>
                    <p>&copy; 2024 Neat Now. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_mail(
            subject=subject,
            message=f'Reset your password:  {reset_url}',
            from_email='afzalrehan@gmail.com',
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )


# ==================== PASSWORD RESET CONFIRM ====================

class PasswordResetConfirmView(APIView):
    """POST /api/admins/password-reset/confirm/ - Confirm password reset"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request. data)
        
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors':  serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        uid = serializer.validated_data['uid']
        token = serializer.validated_data['token']
        new_password = serializer.validated_data['new_password']
        
        try: 
            user_id = force_str(urlsafe_base64_decode(uid))
            user = User.objects.get(pk=user_id)
            
            if not user.is_active:
                return Response({
                    'success': False,
                    'message': 'This account is disabled'
                }, status=status. HTTP_403_FORBIDDEN)
            
            if not default_token_generator.check_token(user, token):
                return Response({
                    'success': False,
                    'message': 'Invalid or expired reset link'
                }, status=status. HTTP_400_BAD_REQUEST)
            
            # Set new password
            user.set_password(new_password)
            user.save()
            
            # Send confirmation email
            try:
                self.send_success_email(user)
            except Exception as e:
                logger. error(f'Failed to send success email: {e}')
            
            logger.info(f'✅ Password reset successful for: {user.email}')
            
            return Response({
                'success': True,
                'message': 'Password reset successfully.  You can now login with your new password.'
            })
            
        except (User.DoesNotExist, ValueError, TypeError):
            return Response({
                'success': False,
                'message': 'Invalid reset link'
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f'Password reset confirm error: {e}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to reset password'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def send_success_email(self, user):
        """Send password reset success confirmation"""
        admin_panel_url = f"{settings.FRONTEND_URL}/admin/login"
        
        subject = '✅ Password Reset Successful'
        
        html_message = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height:  1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background-color: #4CAF50; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 30px; background-color: #f9f9f9; }}
                .button {{ 
                    display: inline-block; 
                    padding: 14px 28px; 
                    background-color:  #4CAF50; 
                    color: white !important; 
                    text-decoration:  none; 
                    border-radius: 5px; 
                    margin: 20px 0;
                    font-weight: bold;
                }}
                .alert {{ 
                    background-color: #f8d7da; 
                    border-left: 4px solid #dc3545; 
                    padding: 12px; 
                    margin: 20px 0;
                }}
                .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>✅ Password Reset Successful</h1>
                </div>
                <div class="content">
                    <p>Hello {user.get_full_name() or user.email},</p>
                    <p>Your password has been reset successfully.</p>
                    
                    <p style="text-align: center;">
                        <a href="{admin_panel_url}" class="button">Login to Admin Panel</a>
                    </p>
                    
                    <div class="alert">
                        <strong>⚠️ Security Alert:</strong> If you did not make this change, 
                        contact support immediately.
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated message, please do not reply.</p>
                    <p>&copy; 2024 Neat Now. All rights reserved.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        send_mail(
            subject=subject,
            message='Your password was reset successfully.',
            from_email='afzalrehan779@gmail.com',
            recipient_list=[user. email],
            html_message=html_message,
            fail_silently=True,
        )


# ==================== DASHBOARD ====================

class DashboardViewSet(viewsets.ViewSet):
    """Dashboard endpoints for admin"""
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated, IsAdmin]
    
    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        """Get dashboard statistics"""
        try:
            logger.info(f'📊 Dashboard stats requested by:  {request.user. email}')
            
            from apps.reports.models import Report
            from apps.workers.models import Worker
            from apps.accounts.models import Account
            
            # Get statistics
            total_reports = Report.objects.count()
            active_workers = Worker.objects.filter(worker_id__is_active=True).count()
            total_citizens = Account.objects.filter(role='Citizen').count()
            
            pending_reports = Report.objects.filter(status='Pending').count()
            in_progress_reports = Report.objects.filter(status='In Progress').count()
            resolved_reports = Report.objects.filter(status='Resolved').count()
            
            # Recent activity
            recent_reports = Report.objects.order_by('-submitted_at')[:5]. count()
            
            stats = {
                'total_reports': total_reports,
                'active_workers': active_workers,
                'total_citizens': total_citizens,
                'pending_reports': pending_reports,
                'in_progress_reports': in_progress_reports,
                'resolved_reports': resolved_reports,
                'recent_activity_count': recent_reports,
            }
            
            logger.info(f'✅ Stats loaded: {stats}')
            
            return Response({
                'success': True,
                'data': stats
            })
            
        except Exception as e:
            logger.error(f'❌ Error loading stats: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to load statistics',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='top-workers')
    def top_workers(self, request):
        """Get top performing workers"""
        try:
            limit = int(request.query_params.get('limit', 5))
            logger.info(f'👷 Top workers requested by: {request.user.email} (limit: {limit})')
            
            from apps.workers. models import Worker
            from apps.workers.serializers import WorkerListSerializer
            
            workers = Worker.objects.select_related('worker_id').filter(
                worker_id__is_active=True
            ).order_by('-avg_rating', '-total_tasks')[:limit]
            
            serializer = WorkerListSerializer(workers, many=True, context={'request': request})
            
            logger.info(f'✅ Loaded {len(serializer.data)} top workers')
            
            return Response({
                'success': True,
                'count': len(serializer.data),
                'data': serializer.data
            })
            
        except Exception as e:
            logger.error(f'❌ Error loading top workers: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to load top workers',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='trends')
    def trends(self, request):
        """Get report trends"""
        try:
            days = int(request.query_params.get('days', 7))
            logger.info(f'📈 Trends requested by: {request. user.email} (days: {days})')
            
            from apps.reports.models import Report
            from django.utils import timezone
            from datetime import timedelta
            from django.db.models import Count
            from django.db.models.functions import TruncDate
            
            start_date = timezone.now() - timedelta(days=days)
            
            trends = Report.objects.filter(
                submitted_at__gte=start_date
            ).annotate(
                date=TruncDate('submitted_at')
            ).values('date').annotate(
                count=Count('report_id')
            ).order_by('date')
            
            data = [
                {
                    'date': item['date']. isoformat(),
                    'count': item['count']
                }
                for item in trends
            ]
            
            logger.info(f'✅ Loaded {len(data)} trend data points')
            
            return Response({
                'success': True,
                'count': len(data),
                'data': data
            })
            
        except Exception as e: 
            logger.error(f'❌ Error loading trends: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to load trends',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=False, methods=['get'], url_path='activities')
    def activities(self, request):
        """Get recent activities"""
        try:
            limit = int(request.query_params.get('limit', 10))
            logger.info(f'📋 Activities requested by: {request. user.email} (limit: {limit})')
            
            from apps.reports.models import Report
            
            reports = Report.objects.select_related(
                'citizen_id', 'worker_id', 'worker_id__worker_id'
            ).order_by('-submitted_at')[:limit]
            
            data = []
            for report in reports: 
                data.append({
                    'id': str(report.report_id),
                    'type': 'report',
                    'action': f'Report {report.status}',
                    'description': f'{report.waste_type} cleanup reported',
                    'timestamp': report.submitted_at.isoformat(),
                    'user': report.citizen_id.name if report.citizen_id else 'Unknown',
                    'worker': report. worker_id.worker_id. name if report.worker_id else None,
                })
            
            logger.info(f'✅ Loaded {len(data)} activities')
            
            return Response({
                'success': True,
                'count': len(data),
                'data': data
            })
            
        except Exception as e:
            logger.error(f'❌ Error loading activities: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Failed to load activities',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== ADMIN CRUD ====================

class AdminViewSet(viewsets.ModelViewSet):
    """ViewSet for managing admin users"""
    authentication_classes = [AdminJWTAuthentication]
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    queryset = Admin.objects.all()
    
    def get_serializer_class(self):
        if self.action == 'create':
            return AdminCreateSerializer
        elif self.action in ['update', 'partial_update']: 
            return AdminUpdateSerializer
        return AdminSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Search
        search = self.request.query_params. get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search)
            )
        
        # Filter by role
        role = self. request.query_params.get('role', None)
        if role:
            queryset = queryset.filter(role=role)
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active', None)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active. lower() == 'true')
        
        return queryset. order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """List all admins"""
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        
        return Response({
            'success': True,
            'count': queryset.count(),
            'data': serializer.data
        })
    
    def retrieve(self, request, *args, **kwargs):
        """Get admin details"""
        instance = self. get_object()
        serializer = self.get_serializer(instance)
        
        return Response({
            'success': True,
            'data': serializer. data
        })
    
    def create(self, request, *args, **kwargs):
        """Create new admin"""
        serializer = self.get_serializer(data=request.data)
        
        if serializer.is_valid():
            admin = serializer.save()
            
            logger.info(f'✅ Admin created: {admin.email}')
            
            return Response({
                'success': True,
                'message': 'Admin created successfully',
                'data': AdminSerializer(admin).data
            }, status=status.HTTP_201_CREATED)
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def update(self, request, *args, **kwargs):
        """Update admin"""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self. get_serializer(instance, data=request.data, partial=partial)
        
        if serializer.is_valid():
            admin = serializer.save()
            
            logger.info(f'✅ Admin updated: {admin.email}')
            
            return Response({
                'success':  True,
                'message': 'Admin updated successfully',
                'data': AdminSerializer(admin).data
            })
        
        return Response({
            'success': False,
            'errors': serializer.errors
        }, status=status.HTTP_400_BAD_REQUEST)
    
    def destroy(self, request, *args, **kwargs):
        """Delete admin"""
        admin = self.get_object()
        
        # Prevent self-deletion
        if admin.admin_id == request.user:
            return Response({
                'success': False,
                'message': 'You cannot delete your own account'
            }, status=status. HTTP_400_BAD_REQUEST)
        
        email = admin.email
        admin. delete()
        
        logger. info(f'✅ Admin deleted: {email}')
        
        return Response({
            'success': True,
            'message': 'Admin deleted successfully'
        })
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle admin active status"""
        admin = self.get_object()
        
        # Prevent self-deactivation
        if admin.admin_id == request.user:
            return Response({
                'success': False,
                'message':  'You cannot deactivate your own account'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        admin.is_active = not admin. is_active
        admin.save()
        
        logger.info(f'✅ Admin {"activated" if admin.is_active else "deactivated"}:  {admin.email}')
        
        return Response({
            'success': True,
            'message': f"Admin {'activated' if admin.is_active else 'deactivated'}",
            'data': AdminSerializer(admin).data
        })