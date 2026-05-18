from rest_framework_simplejwt.tokens import RefreshToken
from datetime import timedelta


def get_tokens_for_admin(admin):
    """
    Generate JWT tokens for admin user
    """
    refresh = RefreshToken()
    
    # Add custom claims
    refresh['admin_id'] = admin.admin_id
    refresh['email'] = admin.email
    refresh['name'] = admin.name
    refresh['role'] = 'admin'
    
    # Set token lifetime
    refresh.access_token. set_exp(lifetime=timedelta(hours=1))
    
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }