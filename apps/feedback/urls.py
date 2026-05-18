from django.urls import path
from .views import FeedbackCreateView, FeedbackListView, WorkerFeedbackDashboardView

urlpatterns = [
    path('create/', FeedbackCreateView.as_view(), name='feedback-create'),
    path('worker/my/', WorkerFeedbackDashboardView.as_view(), name='worker-feedback-dashboard'),
    path('', FeedbackListView.as_view(), name='feedback-list'),
]

