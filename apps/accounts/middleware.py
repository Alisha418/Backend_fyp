from django.utils import timezone
from .models import UserSession


class SessionActivityMiddleware:
    """
    Middleware to update last activity timestamp for active sessions
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Process request
        if request.user.is_authenticated:
            # Update user's last activity
            request.user.update_last_activity()
            
            # Update session's last activity if session_id provided
            session_id = request.META.get('HTTP_X_SESSION_ID')
            if session_id:
                try:
                    session = UserSession.objects.get(
                        session_id=session_id,
                        account=request.user,
                        is_active=True
                    )
                    
                    # Check if session is expired
                    if session.is_expired():
                        session. terminate()
                    else:
                        session.last_activity = timezone.now()
                        session.save(update_fields=['last_activity'])
                        request.session_obj = session
                except UserSession. DoesNotExist:
                    pass
        
        response = self.get_response(request)
        return response