from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ReportViewSet, 
    CitizenReportSubmissionView,
    CitizenVerifyWasteImageView,
    CitizenMyReportsView,
    WorkerAcceptDeclineReportView,
    WorkerMyReportsView,
    WorkerMapSummaryView,
    WorkerUpdateReportStatusView,
    WorkerVerifyCleanupView,
)

router = DefaultRouter()
router.register(r'', ReportViewSet, basename='report')

urlpatterns = [
    # Citizen endpoints
    path('verify_citizen_image/', CitizenVerifyWasteImageView.as_view(), name='verify-citizen-image'),
    path('submit/', CitizenReportSubmissionView.as_view(), name='citizen-submit-report'),
    path('my-reports/', CitizenMyReportsView.as_view(), name='citizen-my-reports'),
    # Worker endpoints
    path('my-tasks/', WorkerMyReportsView.as_view(), name='worker-my-reports'),
    path('map-summary/', WorkerMapSummaryView.as_view(), name='worker-map-summary'),
    path('accept-decline/<int:report_id>/', WorkerAcceptDeclineReportView.as_view(), name='worker-accept-decline'),
    path('worker-verify-cleanup/<int:report_id>/', WorkerVerifyCleanupView.as_view(), name='worker-verify-cleanup'),
    path('worker-update-status/<int:report_id>/', WorkerUpdateReportStatusView.as_view(), name='worker-update-status'),
    # Admin endpoints (ViewSet routes)
    path('', include(router.urls)),
]