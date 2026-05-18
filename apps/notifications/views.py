from rest_framework import viewsets, status
from rest_framework. decorators import action
from rest_framework. response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.authentication import JWTAuthentication
from apps.admins.permissions import IsAdmin
from apps.admins.authentication import AdminJWTAuthentication
from django.utils import timezone
from apps.accounts.models import Account
from .models import Notification, RecipientType
from .serializers import NotificationSerializer
from .display_window import NOTIFICATION_DISPLAY_DAYS, within_notification_display_window
import logging

logger = logging.getLogger(__name__)


def _exclude_worker_report_broadcasts(queryset):
    """
    Admin panel: hide per-worker 'report_available' rows (same citizen report × N workers).
    Workers still receive them in the mobile app; admins get a single citizen_report_pending row.
    """
    return queryset.exclude(
        recipient_type=RecipientType.WORKER,
        message__contains='"type": "report_available"',
    )


class NotificationViewSet(viewsets.ModelViewSet):
    """ViewSet for notifications"""
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated, IsAdmin]
    authentication_classes = [AdminJWTAuthentication]
    lookup_field = 'notification_id'

    def get_queryset(self):
        queryset = Notification.objects.all()

        recipient_type = self.request.query_params.get('recipient_type')

        # Default "all" feed for admins: do not list duplicate worker broadcast rows.
        if not recipient_type or recipient_type.strip().lower() == 'all':
            queryset = _exclude_worker_report_broadcasts(queryset)

        # Filter by recipient type
        if recipient_type and recipient_type.strip().lower() != 'all':
            queryset = queryset.filter(recipient_type=recipient_type)
        
        # Filter by recipient ID
        recipient_id = self.request.query_params. get('recipient_id')
        if recipient_id:
            queryset = queryset.filter(recipient_id=recipient_id)
        
        # Filter by read status
        is_read = self.request. query_params.get('is_read')
        if is_read is not None: 
            queryset = queryset.filter(is_read=is_read. lower() == 'true')

        queryset = within_notification_display_window(queryset)
        return queryset.order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        
        if page is not None:
            serializer = self. get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'success': True,
            'count': queryset.count(),
            'data': serializer.data
        })

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({
            'success':  True,
            'data': serializer. data
        })

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        notification_id = instance. notification_id
        instance.delete()
        return Response({
            'success':  True,
            'message': f'Notification {notification_id} deleted successfully'
        })

    @action(detail=False, methods=['post'])
    def mark_read(self, request):
        """Mark notifications as read"""
        notification_ids = request.data.get('notification_ids', [])
        mark_all = request.data.get('mark_all', False)
        
        if mark_all:
            recipient_type = request.data.get('recipient_type')
            recipient_id = request.data.get('recipient_id')
            
            if not recipient_type or not recipient_id: 
                return Response({
                    'success':  False,
                    'error': 'recipient_type and recipient_id required for mark_all'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            qs = Notification.objects.filter(
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                is_read=False,
            )
            count = within_notification_display_window(qs).update(is_read=True)
        else:
            if not notification_ids: 
                return Response({
                    'success': False,
                    'error': 'notification_ids required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            count = Notification.objects.filter(
                notification_id__in=notification_ids
            ).update(is_read=True)
        
        return Response({
            'success': True,
            'message': f'{count} notifications marked as read'
        })

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        """Get unread notification count"""
        queryset = Notification.objects.filter(is_read=False)
        recipient_type = request.query_params.get('recipient_type')
        if not recipient_type or recipient_type.strip().lower() == 'all':
            queryset = _exclude_worker_report_broadcasts(queryset)
        if recipient_type and recipient_type.strip().lower() != 'all':
            queryset = queryset.filter(recipient_type=recipient_type)

        recipient_id = request.query_params.get('recipient_id')
        if recipient_id:
            queryset = queryset.filter(recipient_id=recipient_id)

        queryset = within_notification_display_window(queryset)
        return Response({
            'success': True,
            'count': queryset.count(),
            'display_days': NOTIFICATION_DISPLAY_DAYS,
        })


# ==================== CITIZEN & WORKER NOTIFICATION ENDPOINTS ====================

class CitizenWorkerNotificationView(APIView):
    """
    APIView for Citizen and Worker notifications
    GET /api/notifications/my/ - Get my notifications
    GET /api/notifications/my/unread_count/ - Get unread count
    POST /api/notifications/my/mark_read/ - Mark notifications as read
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def dispatch(self, request, *args, **kwargs):
        """Override dispatch to log authentication before view method"""
        # ✅ Debug: Log before authentication
        logger.info(f'📥 Notifications API - Request method: {request.method}')
        logger.info(f'📥 Notifications API - Authorization header: {request.META.get("HTTP_AUTHORIZATION", "NOT FOUND")[:50]}...')
        
        try:
            return super().dispatch(request, *args, **kwargs)
        except Exception as e:
            logger.error(f'❌ Notifications API - Error in dispatch: {str(e)}')
            raise
    
    def _get_user_info(self, request):
        """Extract user info from JWT token"""
        user = request.user
        
        # ✅ Debug: Log user object
        logger.info(f'📥 Notifications API - User object: {user}')
        logger.info(f'📥 Notifications API - User type: {type(user)}')
        logger.info(f'📥 Notifications API - User attributes: {dir(user) if hasattr(user, "__dict__") else "N/A"}')
        
        # Handle Account model
        if hasattr(user, 'account_id'):
            account_id = user.account_id
            role = user.role.lower()  # 'Citizen' or 'Worker' -> 'citizen' or 'worker'
            logger.info(f'📥 Notifications API - Account model: ID={account_id}, Role={role}')
            return account_id, role
        
        # Handle dict-like user (from token)
        if isinstance(user, dict):
            account_id = user.get('account_id') or user.get('id')
            role = user.get('role', '').lower()
            logger.info(f'📥 Notifications API - Dict user: ID={account_id}, Role={role}')
            return account_id, role
        
        # Handle TokenUser (from simplejwt)
        if hasattr(user, 'id') or hasattr(user, 'user_id'):
            # Try to get account_id from token claims
            try:
                from rest_framework_simplejwt.tokens import UntypedToken
                from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
                from django.contrib.auth import get_user_model
                
                # Get token from request
                auth_header = request.META.get('HTTP_AUTHORIZATION', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header.split(' ')[1]
                    try:
                        validated_token = UntypedToken(token)
                        account_id = validated_token.get('account_id') or validated_token.get('user_id')
                        role = validated_token.get('role', '').lower()
                        logger.info(f'📥 Notifications API - TokenUser: ID={account_id}, Role={role}')
                        return account_id, role
                    except (InvalidToken, TokenError) as e:
                        logger.error(f'❌ Notifications API - Token validation failed: {str(e)}')
            except Exception as e:
                logger.error(f'❌ Notifications API - Error extracting token info: {str(e)}')
        
        # Fallback
        logger.warning(f'⚠️ Notifications API - Unable to extract user info from: {user}')
        return None, None
    
    def get(self, request):
        """Get notifications for authenticated citizen/worker"""
        # ✅ Debug: Log authentication info
        logger.info(f'📥 Notifications API - User: {request.user}')
        logger.info(f'📥 Notifications API - User type: {type(request.user)}')
        logger.info(f'📥 Notifications API - Is authenticated: {request.user.is_authenticated if hasattr(request.user, "is_authenticated") else "N/A"}')
        
        account_id, role = self._get_user_info(request)
        logger.info(f'📥 Notifications API - Account ID: {account_id}, Role: {role}')
        
        if not account_id or not role:
            logger.warning(f'⚠️ Notifications API - Unable to identify user. Account ID: {account_id}, Role: {role}')
            return Response({
                'success': False,
                'message': 'Unable to identify user'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Map role to recipient_type
        recipient_type_map = {
            'citizen': RecipientType.CITIZEN,
            'worker': RecipientType.WORKER,
        }
        
        recipient_type = recipient_type_map.get(role)
        if not recipient_type:
            return Response({
                'success': False,
                'message': f'Invalid role: {role}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get query parameters
        unread_only = request.query_params.get('unread_only', 'false').lower() == 'true'
        limit = int(request.query_params.get('limit', 50))
        
        # Filter notifications
        queryset = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=account_id
        )
        
        if unread_only:
            queryset = queryset.filter(is_read=False)

        queryset = within_notification_display_window(queryset)
        notifications = list(queryset.order_by('-created_at')[:limit])
        serializer = NotificationSerializer(notifications, many=True)
        
        return Response({
            'success': True,
            'count': len(notifications),
            'display_days': NOTIFICATION_DISPLAY_DAYS,
            'data': serializer.data
        })


class UnreadCountView(APIView):
    """
    GET /api/notifications/my/unread_count/ - Get unread notification count
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _get_user_info(self, request):
        """Extract user info from JWT token"""
        user = request.user
        
        if hasattr(user, 'account_id'):
            account_id = user.account_id
            role = user.role.lower()
            return account_id, role
        
        if isinstance(user, dict):
            account_id = user.get('account_id') or user.get('id')
            role = user.get('role', '').lower()
            return account_id, role
        
        return None, None
    
    def get(self, request):
        """Get unread notification count"""
        account_id, role = self._get_user_info(request)
        
        if not account_id or not role:
            return Response({
                'success': False,
                'message': 'Unable to identify user'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        recipient_type_map = {
            'citizen': RecipientType.CITIZEN,
            'worker': RecipientType.WORKER,
        }
        
        recipient_type = recipient_type_map.get(role)
        if not recipient_type:
            return Response({
                'success': False,
                'message': f'Invalid role: {role}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        qs = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=account_id,
            is_read=False,
        )
        count = within_notification_display_window(qs).count()
        
        return Response({
            'success': True,
            'count': count,
            'display_days': NOTIFICATION_DISPLAY_DAYS,
        })


class MarkNotificationReadView(APIView):
    """
    POST /api/notifications/my/mark_read/ - Mark notifications as read
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]
    
    def _get_user_info(self, request):
        """Extract user info from JWT token"""
        user = request.user
        
        if hasattr(user, 'account_id'):
            account_id = user.account_id
            role = user.role.lower()
            return account_id, role
        
        if isinstance(user, dict):
            account_id = user.get('account_id') or user.get('id')
            role = user.get('role', '').lower()
            return account_id, role
        
        return None, None
    
    def post(self, request):
        """Mark notifications as read"""
        account_id, role = self._get_user_info(request)
        
        if not account_id or not role:
            return Response({
                'success': False,
                'message': 'Unable to identify user'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        recipient_type_map = {
            'citizen': RecipientType.CITIZEN,
            'worker': RecipientType.WORKER,
        }
        
        recipient_type = recipient_type_map.get(role)
        if not recipient_type:
            return Response({
                'success': False,
                'message': f'Invalid role: {role}'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        notification_ids = request.data.get('notification_ids', [])
        mark_all = request.data.get('mark_all', False)
        
        if mark_all:
            qs = Notification.objects.filter(
                recipient_type=recipient_type,
                recipient_id=account_id,
                is_read=False,
            )
            count = within_notification_display_window(qs).update(is_read=True)
        else:
            # Mark specific notifications as read (only if they belong to this user)
            if not notification_ids:
                return Response({
                    'success': False,
                    'message': 'notification_ids required when mark_all is false'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            count = Notification.objects.filter(
                notification_id__in=notification_ids,
                recipient_type=recipient_type,
                recipient_id=account_id,
                is_read=False
            ).update(is_read=True)
        
        return Response({
            'success': True,
            'message': f'{count} notification(s) marked as read',
            'count': count
        })


class ClearAllMyNotificationsView(APIView):
    """
    POST /api/notifications/my/clear_all/ — remove all notifications for the authenticated
    citizen/worker (only their rows).
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_user_info(self, request):
        user = request.user
        if hasattr(user, 'account_id'):
            return user.account_id, user.role.lower()
        if isinstance(user, dict):
            return user.get('account_id') or user.get('id'), (user.get('role') or '').lower()
        return None, None

    def post(self, request):
        account_id, role = self._get_user_info(request)
        if not account_id or not role:
            return Response(
                {'success': False, 'message': 'Unable to identify user'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        recipient_type_map = {
            'citizen': RecipientType.CITIZEN,
            'worker': RecipientType.WORKER,
        }
        recipient_type = recipient_type_map.get(role)
        if not recipient_type:
            return Response(
                {'success': False, 'message': f'Invalid role: {role}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = Notification.objects.filter(
            recipient_type=recipient_type,
            recipient_id=account_id,
        )
        deleted, _ = within_notification_display_window(qs).delete()
        return Response({
            'success': True,
            'message': f'{deleted} notification(s) removed',
            'deleted': deleted,
            'display_days': NOTIFICATION_DISPLAY_DAYS,
        })


class DeleteOneMyNotificationView(APIView):
    """
    DELETE /api/notifications/my/<notification_id>/
    Remove a single notification if it belongs to the authenticated user.
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_user_info(self, request):
        user = request.user
        if hasattr(user, 'account_id'):
            return user.account_id, user.role.lower()
        if isinstance(user, dict):
            return user.get('account_id') or user.get('id'), (user.get('role') or '').lower()
        return None, None

    def delete(self, request, notification_id):
        account_id, role = self._get_user_info(request)
        if not account_id or not role:
            return Response(
                {'success': False, 'message': 'Unable to identify user'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        recipient_type_map = {
            'citizen': RecipientType.CITIZEN,
            'worker': RecipientType.WORKER,
        }
        recipient_type = recipient_type_map.get(role)
        if not recipient_type:
            return Response(
                {'success': False, 'message': f'Invalid role: {role}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        n = Notification.objects.filter(
            notification_id=notification_id,
            recipient_type=recipient_type,
            recipient_id=account_id,
        ).first()
        if not n:
            return Response(
                {'success': False, 'message': 'Notification not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        n.delete()
        return Response(
            {
                'success': True,
                'message': 'Notification deleted',
            },
            status=status.HTTP_200_OK,
        )


class RegisterFcmTokenView(APIView):
    """
    POST /api/notifications/my/fcm_token/
    Body: { "fcm_token": "<device token>" }  — empty string clears token (logout).
    """
    authentication_classes = [JWTAuthentication]
    permission_classes = [IsAuthenticated]

    def _get_user_info(self, request):
        user = request.user
        if hasattr(user, 'account_id'):
            return user.account_id, user.role.lower()
        if isinstance(user, dict):
            account_id = user.get('account_id') or user.get('id')
            role = user.get('role', '').lower()
            return account_id, role
        return None, None

    def post(self, request):
        account_id, role = self._get_user_info(request)
        if not account_id or role not in ('citizen', 'worker'):
            return Response(
                {'success': False, 'message': 'Unable to identify user'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        raw = request.data.get('fcm_token')
        if raw is None:
            return Response(
                {'success': False, 'message': 'fcm_token is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        token = str(raw).strip()
        try:
            account = Account.objects.get(account_id=account_id)
        except Account.DoesNotExist:
            return Response(
                {'success': False, 'message': 'Account not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        if token:
            account.fcm_token = token
        else:
            account.fcm_token = None
        account.fcm_token_updated_at = timezone.now()
        account.save(update_fields=['fcm_token', 'fcm_token_updated_at'])

        logger.info(
            'FCM token %s for account %s (%s)',
            'registered' if token else 'cleared',
            account_id,
            role,
        )
        return Response({
            'success': True,
            'message': 'FCM token saved' if token else 'FCM token cleared',
            'has_token': bool(token),
        })