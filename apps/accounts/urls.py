from django.urls import path, include
from .views import LeaderboardView
from rest_framework.routers import DefaultRouter
from .views import (
    AccountRegistrationView,
    AccountLoginView,
    AccountLogoutView,
    AccountProfileView,
    PasswordChangeView,
    GoogleAuthView,
    ActiveSessionsView,
    TerminateSessionView,
    TerminateAllSessionsView,
    LoginHistoryView,
    AccountViewSet,
    check_email_exists,
    request_password_reset,  # ✅ New
    verify_reset_token,      # ✅ New
    reset_password_confirm,  
    get_phone_by_email,
    PasswordChangeView,
    LeaderboardView,
    MyRankView,
   # UserProfileView,
)

router = DefaultRouter()
router.register('accounts', AccountViewSet, basename='account')

urlpatterns = [
    # Authentication
    path('register/', AccountRegistrationView.as_view(), name='register'),
    path('login/', AccountLoginView.as_view(), name='login'),
    path('logout/', AccountLogoutView.as_view(), name='logout'),
    path('google-auth/', GoogleAuthView.as_view(), name='google-auth'),
    
    # Profile
    path('profile/', AccountProfileView.as_view(), name='profile'),
    path('password-change/', PasswordChangeView.as_view(), name='password-change'),
    
    # Session Management
    path('sessions/', ActiveSessionsView.as_view(), name='active-sessions'),
    path('sessions/<uuid:session_id>/', TerminateSessionView.as_view(), name='terminate-session'),
    path('sessions/terminate-all/', TerminateAllSessionsView.as_view(), name='terminate-all-sessions'),
    path('password-reset/', request_password_reset, name='password-reset'),
    path('verify-reset-token/', verify_reset_token, name='verify-reset-token'),
    path('reset-password-confirm/', reset_password_confirm, name='reset-password-confirm'),
    # Login History
    path('login-history/', LoginHistoryView.as_view(), name='login-history'),
    path('check-email/', check_email_exists, name='check-email'),
    path('phone-by-email/', get_phone_by_email, name='phone-by-email'),
    # ViewSet routes
    path('leaderboard/', LeaderboardView.as_view(), name='leaderboard'),
    path('leaderboard/', LeaderboardView.as_view(), name='leaderboard'),
    path('leaderboard/my-rank/', MyRankView.as_view(), name='my-rank'),
    #path('api/accounts/profile/', UserProfileView.as_view(), name='user-profile'),
    path('api/accounts/password-change/', PasswordChangeView.as_view(), name='password-change'),
    path('', include(router.urls)),
   # path('api/leaderboard/', include('leaderboard.urls')),
]