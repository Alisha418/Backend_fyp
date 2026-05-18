from django. urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    NotificationViewSet,
    CitizenWorkerNotificationView,
    UnreadCountView,
    MarkNotificationReadView,
    ClearAllMyNotificationsView,
    DeleteOneMyNotificationView,
    RegisterFcmTokenView,
)

router = DefaultRouter()
router.register(r'', NotificationViewSet, basename='notification')

urlpatterns = [
    # ✅ Citizen & Worker endpoints - MUST come BEFORE router (URL matching is left-to-right)
    path('my/fcm_token/', RegisterFcmTokenView.as_view(), name='my-fcm-token'),
    path('my/clear_all/', ClearAllMyNotificationsView.as_view(), name='my-notifications-clear-all'),
    path('my/unread_count/', UnreadCountView.as_view(), name='my-unread-count'),
    path('my/mark_read/', MarkNotificationReadView.as_view(), name='mark-notifications-read'),
    path('my/<int:notification_id>/', DeleteOneMyNotificationView.as_view(), name='my-notification-delete'),
    path('my/', CitizenWorkerNotificationView.as_view(), name='my-notifications'),
    
    # Admin endpoints (via router) - Must come AFTER specific paths
    path('', include(router.urls)),
]