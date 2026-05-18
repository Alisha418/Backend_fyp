from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework import exceptions
import logging

logger = logging.getLogger(__name__)

class AdminJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication for Admin users
    Works with Admin model (not Django User)
    """
    
    def authenticate(self, request):
        try:
            header = self.get_header(request)
            if header is None:
                return None
            
            raw_token = self.get_raw_token(header)
            if raw_token is None:
                return None
            
            validated_token = self.get_validated_token(raw_token)
            admin = self.get_admin(validated_token)
            
            if admin is None:
                raise exceptions.AuthenticationFailed('Admin not found')
            
            if not admin.is_active:
                raise exceptions.AuthenticationFailed('Admin account is disabled')
            
            logger.info(f'✅ Admin authenticated: {admin.email}')
            return (admin, validated_token)
            
        except exceptions.AuthenticationFailed:
            raise
        except Exception as e: 
            logger.error(f'❌ Authentication error: {str(e)}')
            return None
    
    def get_admin(self, validated_token):
        """
        Get Admin from validated token
        """
        try: 
            from apps.admins.models import Admin
            
            admin_id = validated_token.get('admin_id')
            
            if not admin_id: 
                logger.error('❌ No admin_id in token')
                raise exceptions.AuthenticationFailed('Invalid token')
            
            logger.debug(f'Getting admin with ID: {admin_id}')
            
            admin = Admin.objects.get(admin_id=admin_id)
            return admin
            
        except Admin. DoesNotExist:
            logger.error(f'❌ Admin {admin_id} not found')
            raise exceptions.AuthenticationFailed('Admin not found')
        except Exception as e:
            logger. error(f'❌ Error getting admin: {str(e)}')
            raise exceptions.AuthenticationFailed('Invalid token')