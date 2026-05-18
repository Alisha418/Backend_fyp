from rest_framework. permissions import BasePermission


class IsAdmin(BasePermission):
    """Permission class to check if user is an admin"""
    
    def has_permission(self, request, view):
        if not request.user:
            return False
        
        if isinstance(request.user, dict):
            return request.user. get('role') == 'admin' and request.user.get('is_authenticated', False)
        
        if hasattr(request.user, 'is_authenticated'):
            return request.user.is_authenticated
        
        return False



class IsSuperAdmin(BasePermission):
    """Permission class for super admin only"""
    
    def has_permission(self, request, view):
        if not request.user:
            return False
        
        if isinstance(request.user, dict):
            return request.user. get('role') == 'super_admin' and request.user. get('is_authenticated', False)
        
        return False
