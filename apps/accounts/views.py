from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from django.db. models import Q
# Add this with your other imports at the top
from django.contrib.auth import update_session_auth_hash
from django.utils import timezone
from django.contrib.auth.hashers import check_password, make_password
from . models import Account, UserSession, LoginHistory
from .email_policy import (
    is_email_reserved_for_admin,
    normalize_account_email,
    ADMIN_EMAIL_RESERVED_MESSAGE,
)
from apps.workers.models import Worker
from .serializers import (
    AccountSerializer,
    AccountDetailSerializer,
    AccountRegistrationSerializer,
    AccountUpdateSerializer,
    AccountLoginSerializer,
    PasswordChangeSerializer,
    GoogleAuthSerializer,
    UserSessionSerializer,
    LoginHistorySerializer
)
import logging
import os
from datetime import timedelta

logger = logging.getLogger(__name__)


# ==================== HELPER FUNCTIONS ====================

def get_client_ip(request):
    """Extract client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META. get('REMOTE_ADDR')
    return ip


def get_device_info(request):
    """Extract device information from request"""
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    # Simple device type detection
    if 'Mobile' in user_agent or 'Android' in user_agent:  
        device_type = 'mobile'
    elif 'Tablet' in user_agent or 'iPad' in user_agent:  
        device_type = 'tablet'
    elif 'Windows' in user_agent or 'Macintosh' in user_agent or 'Linux' in user_agent:
        device_type = 'desktop'
    else:
        device_type = 'unknown'
    
    return {
        'device_type': device_type,
        'user_agent': user_agent
    }


def get_tokens_for_user(account):
    """Generate JWT tokens for user"""
    refresh = RefreshToken.for_user(account)
    
    # Add custom claims
    refresh['account_id'] = account.account_id
    refresh['email'] = account.email
    refresh['name'] = account.name
    refresh['role'] = account. role
    
    return {
        'refresh': str(refresh),
        'access': str(refresh. access_token),
    }


def create_session_for_user(account, request, device_type='unknown', device_name=None):
    """Create a new session for user"""
    # Generate tokens
    tokens = get_tokens_for_user(account)
    
    # Get device info
    device_info = get_device_info(request)
    if device_type == 'unknown':
        device_type = device_info['device_type']
    
    # Create session
    session = UserSession.objects.create(
        account=account,
        refresh_token=tokens['refresh'],
        access_token=tokens['access'],
        device_type=device_type,
        device_name=device_name,
        ip_address=get_client_ip(request),
        user_agent=device_info['user_agent'],
        expires_at=timezone.now() + timedelta(days=7),
        is_active=True
    )
    
    return {
        'refresh': tokens['refresh'],
        'access': tokens['access'],
        'session_id': str(session.session_id)
    }


def log_login_attempt(account, request, status_type, failure_reason=None):
    """Log login attempt"""
    device_info = get_device_info(request)
    
    LoginHistory.objects.create(
        account=account,
        status=status_type,
        ip_address=get_client_ip(request),
        user_agent=device_info['user_agent'],
        device_type=device_info['device_type'],
        failure_reason=failure_reason
    )


# ==================== EMAIL CHECK ENDPOINT ====================
from django.core.mail import send_mail
from django.conf import settings
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from django.contrib. auth.tokens import default_token_generator
import logging

logger = logging.getLogger(__name__)

# ==================== PASSWORD RESET VIEW ====================

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """
    POST /api/accounts/password-reset/
    Request password reset email
    """
    email = request.data.get('email', '').strip().lower()
    
    if not email:
        return Response({
            'success': False,
            'message': 'Email is required'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        account = Account.objects.get(email=email)
        
        # Generate password reset token
        token = default_token_generator.make_token(account)
        uid = urlsafe_base64_encode(force_bytes(account.account_id))
        
        # Create reset link
        reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}/"
        
        # Send email
        subject = 'Reset Your NeatNow Password'
        message = f'''
Hi {account.name},

You requested to reset your password for your NeatNow account.

Click the link below to reset your password: 
{reset_link}

This link will expire in 24 hours.

If you didn't request this, please ignore this email. 

Best regards,
NeatNow Team
        '''
        
        html_message = f'''
<! DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{
            font-family: 'Arial', sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #1DB69D 0%, #16A085 100%);
            color: white;
            padding: 30px;
            text-align: center;
            border-radius: 10px 10px 0 0;
        }}
        .content {{
            background: #f9f9f9;
            padding: 30px;
            border-radius: 0 0 10px 10px;
        }}
        .button {{
            display: inline-block;
            padding: 15px 30px;
            background: #1DB69D;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            margin: 20px 0;
            font-weight: bold;
        }}
        .footer {{
            text-align: center;
            padding:  20px;
            color:  #666;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔒 Reset Your Password</h1>
        </div>
        <div class="content">
            <p>Hi <strong>{account.name}</strong>,</p>
            
            <p>You requested to reset your password for your NeatNow account.</p>
            
            <p>Click the button below to reset your password:</p>
            
            <div style="text-align: center;">
                <a href="{reset_link}" class="button">Reset Password</a>
            </div>
            
            <p>Or copy and paste this link into your browser:</p>
            <p style="background: white; padding: 10px; border-radius: 5px; word-break: break-all;">
                {reset_link}
            </p>
            
            <p><strong>⏰ This link will expire in 24 hours.</strong></p>
            
            <p>If you didn't request this, please ignore this email and your password will remain unchanged.</p>
            
            <p>Best regards,<br>The NeatNow Team</p>
        </div>
        <div class="footer">
            <p>This is an automated email. Please do not reply to this message.</p>
        </div>
    </div>
</body>
</html>
        '''
        
        try:
            send_mail(
                subject,
                message,
                'afzalrehan779@gmail.com',
                [account.email],
                html_message=html_message,
                fail_silently=False,
            )
            
            logger.info(f'✅ Password reset email sent to:  {account.email}')
            
            # Log the attempt
            log_login_attempt(account, request, 'password_reset_requested')
            
            return Response({
                'success': True,
                'message': 'Password reset email sent successfully'
            })
            
        except Exception as e:
            logger.error(f'❌ Failed to send email: {str(e)}')
            return Response({
                'success': False,
                'message':  'Failed to send email. Please try again later.'
            }, status=status. HTTP_500_INTERNAL_SERVER_ERROR)
    
    except Account.DoesNotExist:
        # Don't reveal if email exists (security best practice)
        # But still return success to prevent email enumeration
        logger.warning(f'⚠️ Password reset requested for non-existent email: {email}')
        
        return Response({
            'success': True,
            'message':  'If that email exists, a reset link has been sent.'
        })
    
    except Exception as e: 
        logger.error(f'❌ Password reset error: {str(e)}', exc_info=True)
        return Response({
            'success':  False,
            'message': 'An error occurred.  Please try again.'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_reset_token(request):
    """
    POST /api/accounts/verify-reset-token/
    Verify if password reset token is valid
    """
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str
    
    uid = request.data.get('uid')
    token = request.data. get('token')
    
    if not uid or not token: 
        return Response({
            'success': False,
            'message':  'Invalid reset link'
        }, status=status. HTTP_400_BAD_REQUEST)
    
    try:
        account_id = force_str(urlsafe_base64_decode(uid))
        account = Account.objects.get(account_id=account_id)
        
        if default_token_generator.check_token(account, token):
            return Response({
                'success': True,
                'message': 'Token is valid'
            })
        else:
            return Response({
                'success': False,
                'message': 'Reset link has expired or is invalid'
            }, status=status.HTTP_400_BAD_REQUEST)
    
    except (Account.DoesNotExist, ValueError, TypeError):
        return Response({
            'success': False,
            'message': 'Invalid reset link'
        }, status=status. HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_confirm(request):
    """
    POST /api/accounts/reset-password-confirm/
    Reset password with token
    """
    from django.utils.http import urlsafe_base64_decode
    from django.utils.encoding import force_str
    
    uid = request.data.get('uid')
    token = request.data.get('token')
    new_password = request.data.get('new_password')
    
    if not uid or not token or not new_password:
        return Response({
            'success': False,
            'message': 'Missing required fields'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        account_id = force_str(urlsafe_base64_decode(uid))
        account = Account.objects.get(account_id=account_id)
        
        if not default_token_generator.check_token(account, token):
            return Response({
                'success':  False,
                'message': 'Reset link has expired or is invalid'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate password strength
        if len(new_password) < 8:
            return Response({
                'success': False,
                'message': 'Password must be at least 8 characters'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Set new password
        account.set_password(new_password)
        account.save()
        
        # Terminate all active sessions
        UserSession.objects.filter(account=account, is_active=True).update(is_active=False)
        
        # Log the change
        log_login_attempt(account, request, 'password_reset_completed')
        
        logger.info(f'✅ Password reset completed for: {account. email}')
        
        return Response({
            'success': True,
            'message': 'Password reset successfully.  Please login with your new password.'
        })
    
    except (Account.DoesNotExist, ValueError, TypeError):
        return Response({
            'success': False,
            'message': 'Invalid reset link'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    except Exception as e: 
        logger.error(f'❌ Password reset confirm error: {str(e)}', exc_info=True)
        return Response({
            'success':  False,
            'message': 'An error occurred. Please try again.'
        }, status=status. HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_with_firebase_phone(request):
    """
    POST /api/reset-password/
    Forgot password via Firebase Phone OTP:
    - Flutter sends: phone_number + firebase_id_token + new_password (+ password_confirm)
    - Backend verifies firebase_id_token using firebase-admin
    - If valid, updates account password for that phone_number
    """
    import re
    import json as _json

    phone_number = request.data.get('phone_number', '').strip()
    firebase_id_token = (
        request.data.get('firebase_id_token')
        or request.data.get('idToken')
        or request.data.get('id_token')
        or ''
    ).strip()
    new_password = request.data.get('new_password') or ''
    password_confirm = request.data.get('password_confirm')  # optional

    if not phone_number or not firebase_id_token or not new_password:
        return Response(
            {'success': False, 'message': 'Missing required fields'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if password_confirm is not None and password_confirm != new_password:
        return Response(
            {'success': False, 'message': 'Passwords do not match'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(new_password) < 8:
        return Response(
            {'success': False, 'message': 'Password must be at least 8 characters'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _normalize_phone(p: str) -> str:
        # Compare by digits only to avoid formatting differences (+92 vs 0092 etc.)
        return re.sub(r'\D', '', (p or ''))

    # Import firebase-admin lazily so server boots even if dependency isn't installed
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
        from firebase_admin import credentials as firebase_credentials
    except ModuleNotFoundError:
        return Response(
            {
                'success': False,
                'message': 'Server missing dependency: firebase-admin. Install it first.'
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Initialize firebase-admin (needs service account)
    if not firebase_admin._apps:
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
        if service_account_json:
            try:
                cred = firebase_credentials.Certificate(_json.loads(service_account_json))
                firebase_admin.initialize_app(cred)
            except Exception as e:
                return Response(
                    {
                        'success': False,
                        'message': 'Invalid FIREBASE_SERVICE_ACCOUNT_JSON',
                        'error': str(e),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        else:
            # Fallback: GOOGLE_APPLICATION_CREDENTIALS must point to service account file
            try:
                firebase_admin.initialize_app()
            except Exception as e:
                return Response(
                    {
                        'success': False,
                        'message': 'Firebase service account not configured. Set FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS.',
                        'error': str(e),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

    # Verify the Firebase ID token
    try:
        decoded = firebase_auth.verify_id_token(firebase_id_token, check_revoked=False)
    except Exception as e:
        return Response(
            {'success': False, 'message': 'Invalid or expired Firebase token', 'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_phone = decoded.get('phone_number') or decoded.get('phone') or ''
    if not token_phone:
        return Response(
            {'success': False, 'message': 'Token payload missing phone_number claim'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if _normalize_phone(token_phone) != _normalize_phone(phone_number):
        return Response(
            {'success': False, 'message': 'Phone number does not match token payload'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Find account by phone_number
    account = Account.objects.filter(phone_number=phone_number).first()
    if account is None:
        # Fallback: compare by digits only (formatting differences)
        requested_digits = _normalize_phone(phone_number)
        for acc in Account.objects.filter(phone_number__isnull=False).exclude(phone_number=''):
            if _normalize_phone(acc.phone_number or '') == requested_digits:
                account = acc
                break

    if account is None:
        return Response(
            {'success': False, 'message': 'No account found for this phone number'},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Update password
    account.set_password(new_password)
    account.save()

    # Terminate all active sessions for this user
    UserSession.objects.filter(account=account, is_active=True).update(is_active=False)

    # Log the change
    log_login_attempt(account, request, 'password_reset_completed')
    logger.info(f'✅ Phone/Firebase password reset completed for: {account.phone_number}')

    return Response(
        {
            'success': True,
            'message': 'Password reset successfully. Please login with your new password.',
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def get_phone_by_email(request):
    """
    POST /api/accounts/phone-by-email/
    Body: { "email": "user@example.com" }
    Returns the account's phone_number so Flutter can send OTP to phone.
    """
    email = (request.data.get('email') or '').strip().lower()
    if not email:
        return Response(
            {'success': False, 'message': 'Email is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account = Account.objects.filter(email=email).first()
    if account is None:
        return Response(
            {'success': False, 'message': 'No account found for this email'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not account.phone_number:
        return Response(
            {'success': False, 'message': 'This account does not have a phone number'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {'success': True, 'phone_number': account.phone_number},
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_with_firebase_phone_by_email(request):
    """
    POST /api/reset-password-by-email/
    Body: { "email": "...", "firebase_id_token": "...", "new_password": "...", "password_confirm"?: "..." }
    Verifies firebase_id_token on server, then updates password for the account that matches email.
    """
    import re
    import json as _json

    email = (request.data.get('email') or '').strip().lower()
    firebase_id_token = (
        request.data.get('firebase_id_token')
        or request.data.get('idToken')
        or request.data.get('id_token')
        or ''
    ).strip()
    new_password = request.data.get('new_password') or ''
    password_confirm = request.data.get('password_confirm')

    if not email or not firebase_id_token or not new_password:
        return Response(
            {'success': False, 'message': 'Missing required fields'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if password_confirm is not None and password_confirm != new_password:
        return Response(
            {'success': False, 'message': 'Passwords do not match'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(new_password) < 8:
        return Response(
            {'success': False, 'message': 'Password must be at least 8 characters'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _normalize_phone(p: str) -> str:
        return re.sub(r'\D', '', (p or ''))

    # Import firebase-admin lazily
    try:
        import firebase_admin
        from firebase_admin import auth as firebase_auth
        from firebase_admin import credentials as firebase_credentials
    except ModuleNotFoundError:
        return Response(
            {
                'success': False,
                'message': 'Server missing dependency: firebase-admin. Install it first.',
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # Initialize firebase-admin (needs service account)
    if not firebase_admin._apps:
        service_account_json = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON', '').strip()
        if service_account_json:
            try:
                cred = firebase_credentials.Certificate(_json.loads(service_account_json))
                firebase_admin.initialize_app(cred)
            except Exception as e:
                return Response(
                    {
                        'success': False,
                        'message': 'Invalid FIREBASE_SERVICE_ACCOUNT_JSON',
                        'error': str(e),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        else:
            try:
                firebase_admin.initialize_app()
            except Exception as e:
                return Response(
                    {
                        'success': False,
                        'message': 'Firebase service account not configured. Set FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS.',
                        'error': str(e),
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

    # Verify Firebase token
    try:
        decoded = firebase_auth.verify_id_token(firebase_id_token, check_revoked=False)
    except Exception as e:
        return Response(
            {'success': False, 'message': 'Invalid or expired Firebase token', 'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    token_phone = decoded.get('phone_number') or decoded.get('phone') or ''
    if not token_phone:
        return Response(
            {'success': False, 'message': 'Token payload missing phone_number claim'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account = Account.objects.filter(email=email).first()
    if account is None:
        return Response(
            {'success': False, 'message': 'No account found for this email'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if not account.phone_number:
        return Response(
            {'success': False, 'message': 'This account does not have a phone number'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if _normalize_phone(token_phone) != _normalize_phone(account.phone_number):
        return Response(
            {'success': False, 'message': 'Phone number does not match token payload'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    account.set_password(new_password)
    account.save()

    UserSession.objects.filter(account=account, is_active=True).update(is_active=False)
    log_login_attempt(account, request, 'password_reset_completed')
    logger.info(f'✅ Email/Firebase password reset completed for: {account.email}')

    return Response(
        {
            'success': True,
            'message': 'Password reset successfully. Please login with your new password.',
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def check_email_exists(request):
    """
    POST /api/accounts/check-email/
    Check if email already exists
    """
    email = request.data.get('email', '').strip().lower()
    
    if not email:
        return Response({
            'exists': False,
            'reserved_for_admin': False,
            'message':  'Email is required'
        }, status=status.HTTP_400_BAD_REQUEST)

    if is_email_reserved_for_admin(email):
        return Response({
            'exists': True,
            'reserved_for_admin': True,
            'message': ADMIN_EMAIL_RESERVED_MESSAGE,
        })

    exists = Account.objects.filter(email=email).exists()
    
    return Response({
        'exists': exists,
        'reserved_for_admin': False,
        'message':  'Email already registered' if exists else 'Email available'
    })


# ==================== AUTHENTICATION VIEWS ====================

class AccountRegistrationView(APIView):
    """
    POST /api/accounts/register/
    Register new user account
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = AccountRegistrationSerializer(data=request.data)
        
        if not serializer.is_valid():
            logger.error(f'❌ Registration validation failed: {serializer.errors}')
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            account = serializer.save()
            
            # Create session
            device_type = request.data.get('device_type', 'unknown')
            device_name = request. data.get('device_name')
            tokens = create_session_for_user(account, request, device_type, device_name)
            
            logger.info(f'✅ New account registered: {account.email}')
            
            return Response({
                'success': True,
                'message': 'Account created successfully',
                'data': {
                    'account': AccountSerializer(account).data,
                    'access_token': tokens['access'],
                    'refresh_token': tokens['refresh'],
                    'session_id': tokens['session_id']
                }
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e: 
            logger.error(f'❌ Registration error: {str(e)}')
            return Response({
                'success': False,
                'message':  'Registration failed.  Please try again.',
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

import logging

logger = logging.getLogger(__name__)

class AccountLoginView(APIView):
    """
    POST /api/accounts/login/
    User login endpoint with session management
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        logger.info(f'📥 Login request received')
        logger.info(f'📝 Request data: {request.data}')
        
        serializer = AccountLoginSerializer(data=request.data)
        
        if not serializer.is_valid():
            logger.error(f'❌ Serializer validation failed: {serializer.errors}')
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        email = serializer.validated_data['email']
        password = serializer.validated_data['password']
        
        logger.info(f'🔍 Attempting login for:  {email}')
        
        try:
            account = Account.objects.get(email=email. lower())
            logger.info(f'✅ Account found: {account. email}, Role: {account.role}')
        except Account.DoesNotExist:
            logger.warning(f'⚠️ Account not found:  {email}')
            return Response({
                'success': False,
                'message': 'Invalid email or password'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        # Check if account is active
        if not account.is_active:
            logger.warning(f'⚠️ Account disabled: {email}')
            log_login_attempt(account, request, 'blocked', 'Account is disabled')
            return Response({
                'success': False,
                'message': 'You can not login into your account because you are deactivate by Admin.'
            }, status=status. HTTP_403_FORBIDDEN)
        
        # Verify password
        logger.info(f'🔐 Checking password for: {email}')
        if not account.check_password(password):
            logger.error(f'❌ Password check failed for: {email}')
            log_login_attempt(account, request, 'failed', 'Invalid password')
            return Response({
                'success': False,
                'message': 'Invalid email or password'
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        try:
            # Update last login
            account.last_login = timezone.now()
            account.save(update_fields=['last_login'])
            
            # Create session
            logger.info(f'🎫 Creating session for: {email}')
            tokens = create_session_for_user(account, request, 'unknown', None)
            log_login_attempt(account, request, 'success')
            
            logger.info(f'✅ Login successful: {email}')
            
            return Response({
                'success': True,
                'message': 'Login successful',
                'data': {
                    'account':  AccountDetailSerializer(account).data,
                    'access_token': tokens['access'],
                    'refresh_token':  tokens['refresh'],
                    'session_id': tokens['session_id']
                }
            })
        except Exception as e:
            logger. error(f'❌ Login error: {str(e)}', exc_info=True)
            return Response({
                'success': False,
                'message': 'Login failed.  Please try again.'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class AccountLogoutView(APIView):
    """
    POST /api/accounts/logout/
    Logout user and terminate session
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        session_id = request.data.get('session_id')
        
        if session_id:
            # Terminate specific session
            try: 
                session = UserSession.objects.get(
                    session_id=session_id,
                    account=request.user,
                    is_active=True
                )
                session.terminate()
                message = 'Session terminated successfully'
            except UserSession.DoesNotExist:
                message = 'Session not found'
        else:
            # Terminate all active sessions
            sessions = UserSession.objects.filter(
                account=request.user,
                is_active=True
            )
            for session in sessions: 
                session.terminate()
            message = 'All sessions terminated successfully'

        # Worker: clear tracking in DB (same as POST /api/workers/tracking/ is_tracking=false).
        # This is "offline / not on duty" — not Account.is_active (that remains True so they can
        # log in again; only admins toggle is_active to disable accounts).
        if getattr(request.user, 'role', None) == 'Worker':
            try:
                w = Worker.objects.get(worker_id=request.user)
                if w.is_tracking:
                    w.is_tracking = False
                    w.save(update_fields=['is_tracking'])
            except Worker.DoesNotExist:
                pass
        
        logger.info(f'✅ User logged out: {request.user.email}')
        
        return Response({
            'success': True,
            'message': message
        })



class AccountProfileView(APIView):
    """
    GET/PATCH /api/accounts/profile/
    Get and update user profile
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get current user profile"""
        account = request.user
        
        return Response({
            'success': True,
            'user': {
                'account_id': account.account_id,
                'email': account.email,
                'name': account.name,
                'phone_number': account.phone_number,
                'profile_image': account.profile_image. url if account.profile_image else None,
                'role': account.role,
                'created_at': account.created_at.isoformat(),
                'last_login': account.last_login.isoformat() if account.last_login else None,
            }
        })
    
    def patch(self, request):
        """Update user profile"""
        account = request.user
        
        # Update name
        if 'name' in request.data:
            name = request.data['name']. strip()
            if len(name) < 2:
                return Response({
                    'success': False,
                    'message': 'Name must be at least 2 characters'
                }, status=status.HTTP_400_BAD_REQUEST)
            account.name = name
        
        # Update phone number
        if 'phone_number' in request.data:
            phone = request.data['phone_number'].strip()
            if not phone:
                return Response(
                    {
                        'success': False,
                        'message': 'Phone number is required'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            import re
            digits = re.sub(r'\D', '', phone)
            canonical = None
            # Examples:
            # - 0347xxxxxxxx -> +92347xxxxxxxx
            # - +92347xxxxxxxx -> +92347xxxxxxxx
            if phone.startswith('+'):
                if digits.startswith('92') and len(digits) == 12:
                    canonical = '+92' + digits[2:]
            else:
                if digits.startswith('0') and len(digits) == 11:
                    canonical = '+92' + digits[1:]
                elif digits.startswith('92') and len(digits) == 12:
                    canonical = '+92' + digits[2:]

            if canonical is None or not re.match(r'^\+92\d{10}$', canonical):
                return Response(
                    {
                        'success': False,
                        'message': 'Phone number must be in format +92XXXXXXXXXX'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            account.phone_number = canonical
        
        # Update profile image
        if 'profile_image' in request.FILES:
            # Delete old image if exists
            if account.profile_image:
                account.profile_image.delete(save=False)
            
            account.profile_image = request.FILES['profile_image']
        
        # Save changes
        account. save()
        
        logger.info(f'✅ Profile updated:  {account.email}')
        
        return Response({
            'success': True,
            'message':  'Profile updated successfully',
            'user': {
                'account_id': account.account_id,
                'email': account. email,
                'name': account.name,
                'phone_number': account.phone_number,
                'profile_image': account.profile_image.url if account.profile_image else None,
                'role': account.role,
                'created_at': account.created_at.isoformat(),
                'last_login':  account.last_login.isoformat() if account.last_login else None,
            }
        })

class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            user = request.user
            current_password = request.data.get('current_password')
            new_password = request.data.get('new_password')

            print(f'📥 Password change request for user: {user.email}')
            print(f'📥 Current password provided: {bool(current_password)}')
            print(f'📥 New password provided: {bool(new_password)}')

            # Validate input
            if not current_password or not new_password:
                return Response(
                    {
                        'success': False,
                        'message': 'Both current and new password are required'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ✅ Check if your User model uses 'password_hash' or 'password'
            # If using custom 'password_hash' field: 
            if hasattr(user, 'password_hash'):
                password_field = user.password_hash
            else:
                password_field = user.password

            # Check if current password is correct
            if not check_password(current_password, password_field):
                print('Current password is incorrect')
                return Response(
                    {
                        'success':  False,
                        'message':  'Current password is incorrect'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Validate new password
            if len(new_password) < 8:
                return Response(
                    {
                        'success': False,
                        'message': 'New password must be at least 8 characters'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if new password has uppercase
            if not any(c.isupper() for c in new_password):
                return Response(
                    {
                        'success': False,
                        'message': 'Password must contain an uppercase letter'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if new password has number
            if not any(c. isdigit() for c in new_password):
                return Response(
                    {
                        'success': False,
                        'message': 'Password must contain a number'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Check if new password is different from current
            if current_password == new_password: 
                return Response(
                    {
                        'success': False,
                        'message': 'New password must be different from current password'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            # ✅ Update password based on your User model field
            if hasattr(user, 'password_hash'):
                user.password_hash = make_password(new_password)
            else:
                user.set_password(new_password)
            
            user.save()

            print(f'✅ Password changed successfully for user:  {user.email}')

            # Keep user logged in after password change
            update_session_auth_hash(request, user)

            return Response(
                {
                    'success': True,
                    'message': 'Password changed successfully'
                },
                status=status. HTTP_200_OK
            )

        except Exception as e: 
            print(f'Password change error: {str(e)}')
            import traceback
            traceback.print_exc()
            return Response(
                {
                    'success': False,
                    'message': f'An error occurred: {str(e)}'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class GoogleAuthView(APIView):
    """
    POST /api/accounts/google-auth/
    Google OAuth login/register
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        
        if not serializer.is_valid():
            print('[GoogleAuthView] Invalid payload keys:', list(getattr(request, 'data', {}).keys()))
            print('[GoogleAuthView] Serializer errors:', serializer.errors)
            return Response({
                'success':  False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        google_token = serializer.validated_data['google_token']
        role = serializer.validated_data['role']
        print('[GoogleAuthView] Valid Google payload received. role:', role, 'google_token_len:', len(google_token or ''))
        device_type = serializer.validated_data.get('device_type', 'unknown')
        device_name = serializer.validated_data.get('device_name')
        
        # Verify Google ID token and extract user info.
        google_client_id = os.getenv('GOOGLE_CLIENT_ID')
        if not google_client_id:
            return Response(
                {'success': False, 'message': 'Server misconfigured: GOOGLE_CLIENT_ID missing.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            from google.oauth2 import id_token
            from google.auth.transport.requests import Request as GoogleRequest
        except ModuleNotFoundError:
            return Response(
                {'success': False, 'message': 'Server missing dependency: google-auth.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        try:
            id_info = id_token.verify_oauth2_token(
                google_token,
                GoogleRequest(),
                audience=google_client_id,
            )
        except Exception as e:
            return Response(
                {'success': False, 'message': 'Invalid Google token.', 'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

        google_user_data = {
            'google_id': id_info.get('sub'),
            'email': id_info.get('email'),
            'name': id_info.get('name')
            or f"{id_info.get('given_name','')} {id_info.get('family_name','')}".strip(),
            'profile_image': id_info.get('picture'),
        }

        if not google_user_data['google_id'] or not google_user_data['email']:
            return Response(
                {'success': False, 'message': 'Google token payload missing required fields.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not google_user_data['name']:
            google_user_data['name'] = google_user_data['email']

        google_email = normalize_account_email(google_user_data['email'])
        if is_email_reserved_for_admin(google_email):
            return Response(
                {
                    'success': False,
                    'message': ADMIN_EMAIL_RESERVED_MESSAGE,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if user exists (by google_id first, then fallback to email).
        account = None
        try:
            account = Account.objects.get(google_id=google_user_data['google_id'])
        except Account.DoesNotExist:
            pass

        if account is None:
            account = Account.objects.filter(email=google_user_data['email']).first()

        if account:
            # Existing user: sync profile only — do NOT overwrite role from the app
            # (Google button always sent role=Citizen and was flipping workers to citizens).
            account.google_id = google_user_data['google_id']
            account.email = google_user_data['email']
            account.name = google_user_data['name']
            account.is_active = True
            update_fields = ['google_id', 'email', 'name', 'is_active']
            if Worker.objects.filter(worker_id=account).exists():
                if account.role != 'Worker':
                    account.role = 'Worker'
                    update_fields.append('role')
            account.save(update_fields=update_fields)
        else:
            signup_role = 'Worker' if str(role).lower() == 'worker' else 'Citizen'
            account = Account.objects.create(
                email=google_user_data['email'],
                name=google_user_data['name'],
                role=signup_role,
                google_id=google_user_data['google_id'],
                is_active=True
            )
            logger.info(f'✅ New Google user registered: {account.email}')
        
        # Create session
        tokens = create_session_for_user(account, request, device_type, device_name)
        log_login_attempt(account, request, 'success')
        
        return Response({
            'success': True,
            'message':  'Login successful',
            'data': {
                'account': AccountDetailSerializer(account).data,
                'access_token': tokens['access'],
                'refresh_token': tokens['refresh'],
                'session_id': tokens['session_id']
            }
        })


# ==================== SESSION MANAGEMENT VIEWS ====================

class ActiveSessionsView(APIView):
    """
    GET /api/accounts/sessions/
    Get all active sessions for current user
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        sessions = UserSession.objects.filter(
            account=request.user,
            is_active=True
        ).order_by('-last_activity')
        
        serializer = UserSessionSerializer(
            sessions,
            many=True,
            context={'request': request}
        )
        
        return Response({
            'success':  True,
            'data': serializer.data,
            'total': sessions.count()
        })


class TerminateSessionView(APIView):
    """
    DELETE /api/accounts/sessions/<session_id>/
    Terminate a specific session
    """
    permission_classes = [IsAuthenticated]
    
    def delete(self, request, session_id):
        try:
            session = UserSession.objects.get(
                session_id=session_id,
                account=request.user
            )
            session.terminate()
            
            return Response({
                'success': True,
                'message': 'Session terminated successfully'
            })
        except UserSession.DoesNotExist:
            return Response({
                'success': False,
                'message': 'Session not found'
            }, status=status.HTTP_404_NOT_FOUND)


class TerminateAllSessionsView(APIView):
    """
    POST /api/accounts/sessions/terminate-all/
    Terminate all sessions except current
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        current_session_id = request.data.get('session_id')
        
        sessions = UserSession.objects.filter(
            account=request.user,
            is_active=True
        )
        
        terminated_count = 0
        for session in sessions: 
            if str(session.session_id) != current_session_id:
                session.terminate()
                terminated_count += 1
        
        return Response({
            'success': True,
            'message': f'{terminated_count} session(s) terminated successfully',
            'terminated_count': terminated_count
        })


class LoginHistoryView(APIView):
    """
    GET /api/accounts/login-history/
    Get login history for current user
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        limit = int(request.query_params.get('limit', 20))
        
        history = LoginHistory.objects.filter(
            account=request.user
        ).order_by('-attempted_at')[:limit]
        
        serializer = LoginHistorySerializer(history, many=True)
        
        return Response({
            'success': True,
            'data':  serializer.data,
            'total': history.count()
        })


# ==================== ADMIN VIEWSET ====================

class AccountViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing user accounts (admin only)
    """
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]  # Add admin permission in production
    
    def get_serializer_class(self):
        if self.action == 'retrieve':
            return AccountDetailSerializer
        elif self.action == 'create':
            return AccountRegistrationSerializer
        elif self.action in ['update', 'partial_update']:
            return AccountUpdateSerializer
        return AccountSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by role
        role = self.request.query_params.get('role', None)
        if role:
            queryset = queryset.filter(role=role)
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active', None)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active. lower() == 'true')
        
        # Search
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(email__icontains=search) |
                Q(phone_number__icontains=search)
            )
        
        return queryset. order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle account active status"""
        account = self. get_object()
        account.is_active = not account.is_active
        account.save()
        
        # Terminate all sessions if deactivated
        if not account. is_active:
            sessions = UserSession.objects.filter(account=account, is_active=True)
            for session in sessions:
                session.terminate()
        
        return Response({
            'success': True,
            'message': f"Account {'activated' if account.is_active else 'deactivated'}",
            'data': AccountSerializer(account).data
        })
    
    @action(detail=True, methods=['get'])
    def sessions(self, request, pk=None):
        """Get all sessions for a specific account"""
        account = self. get_object()
        sessions = UserSession.objects.filter(account=account).order_by('-last_activity')
        serializer = UserSessionSerializer(sessions, many=True, context={'request': request})
        
        return Response({
            'success': True,
            'data':  serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def login_history(self, request, pk=None):
        """Get login history for a specific account"""
        account = self.get_object()
        limit = int(request.query_params.get('limit', 50))
        
        history = LoginHistory.objects. filter(account=account).order_by('-attempted_at')[:limit]
        serializer = LoginHistorySerializer(history, many=True)
        
        return Response({
            'success': True,
            'data': serializer.data
        })
class LeaderboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit_param = request.GET.get('limit', '50')
            limit = int(limit_param) if limit_param.isdigit() else 50
            period = request.GET.get('period', 'all_time')

            # Avoid emoji in console output (Windows encoding can crash and cause 500).
            print(f'Leaderboard request - Limit: {limit}, Period: {period}')
            from django.contrib.auth import get_user_model
            from django.db.models import Count, Q
            User = get_user_model()
            
            # Get users with total submitted reports count (all reports including pending are considered verified)
            # Only show users who have submitted at least one report
            users = User.objects.filter(
                role='Citizen',
                is_active=True
            ).annotate(
                verified_reports_count=Count(
                    'submitted_reports',
                    filter=Q(submitted_reports__report_source='citizen'),
                ),
            ).filter(
                verified_reports_count__gt=0  # Only users with at least 1 report
            ).order_by('-verified_reports_count')
            
            # Apply limit only if specified and reasonable
            # If limit is 0, return all users with reports (for full leaderboard)
            if limit > 0:
                users = users[:limit]
            # If limit is 0, return all users (no slicing)

            leaderboard_data = []
            # Convert queryset to list to avoid issues
            users_list = list(users)
            
            for index, user in enumerate(users_list, start=1):
                # Determine badge based on rank (most reports = rank 1 = platinum)
                # User with most reports gets platinum, regardless of total users
                badge = None
                if index == 1:
                    # Rank 1 (most reports) always gets platinum
                    badge = 'platinum'
                elif index == 2:
                    # Rank 2 gets gold
                    badge = 'gold'
                elif index == 3:
                    # Rank 3 gets silver
                    badge = 'silver'
                # Rank 4+ gets no badge (None)

                # Safely get profile image URL
                avatar_url = None
                if user.profile_image:
                    try:
                        avatar_url = user.profile_image.url
                    except (AttributeError, ValueError):
                        avatar_url = None

                leaderboard_data.append({
                    'id': str(user.account_id),  # Frontend expects 'id' as string
                    'account_id': user.account_id,  # Keep for compatibility
                    'name': user.name or 'Unknown',
                    'verified_reports': user.verified_reports_count or 0,  # All submitted reports (verified = submitted)
                    'rank': index,
                    'badge': badge,
                    'avatar_url': avatar_url,  # Frontend expects 'avatar_url'
                    'profile_image': avatar_url,  # Keep for compatibility
                })

            return Response({
                'success': True,
                'data': leaderboard_data,
                'message': f'Leaderboard loaded successfully'
            })

        except Exception as e:
            print(f'Leaderboard error: {str(e)}')
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class MyRankView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            from django.contrib.auth import get_user_model
            from django.db.models import Count, Q
            User = get_user_model()
            
            user = request.user

            # Get user's total reports count (citizen-submitted only)
            user_reports_count = user.submitted_reports.filter(report_source='citizen').count()
            
            # Get user's rank (count users with more reports)
            # Only count users who have submitted at least 1 report
            if user_reports_count == 0:
                # User has no reports, so no rank
                rank = 0
            else:
                # Count users with more reports (and at least 1 report)
                users_above = User.objects.filter(
                    role='Citizen',
                    is_active=True
                ).annotate(
                    verified_reports_count=Count(
                        'submitted_reports',
                        filter=Q(submitted_reports__report_source='citizen'),
                    ),
                ).filter(
                    verified_reports_count__gt=user_reports_count  # More reports than current user
                ).count()
                
                rank = users_above + 1

            # Get total users with reports for percentile calculation
            total_users_with_reports = User.objects.filter(
                role='Citizen',
                is_active=True
            ).annotate(
                verified_reports_count=Count(
                    'submitted_reports',
                    filter=Q(submitted_reports__report_source='citizen'),
                ),
            ).filter(
                verified_reports_count__gt=0
            ).count()
            
            percentile = ((total_users_with_reports - rank) / total_users_with_reports * 100) if total_users_with_reports > 0 else 0

            return Response({
                'success':  True,
                'rank': rank,
                'verified_reports':  user_reports_count,  # Total submitted reports
                'percentile': round(percentile, 1),
            })

        except Exception as e: 
            print(f'Error getting rank: {str(e)}')
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )