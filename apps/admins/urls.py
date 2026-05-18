from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .  views import (
    admin_login,  # ✅ Changed from AdminLoginView
    AdminProfileView,
    AdminPasswordChangeView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    AdminViewSet,
    DashboardViewSet,
)

# Router for viewsets
router = DefaultRouter()
router.register(r'admins', AdminViewSet, basename='admin')
router.register(r'dashboard', DashboardViewSet, basename='dashboard')

urlpatterns = [
    # ==================== AUTHENTICATION ====================
    path('login/', admin_login, name='admin-login'),  # ✅ Function-based view
    path('profile/', AdminProfileView. as_view(), name='admin-profile'),
    path('password-change/', AdminPasswordChangeView.as_view(), name='admin-password-change'),
    
    # Password Reset
    path('password-reset/request/', PasswordResetRequestView.as_view(), name='password-reset-request'),
    path('password-reset/confirm/', PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    
    # Token Refresh
    path('token/refresh/', TokenRefreshView. as_view(), name='token-refresh'),
    
    # ==================== VIEWSETS ====================
    path('', include(router.urls)),
]