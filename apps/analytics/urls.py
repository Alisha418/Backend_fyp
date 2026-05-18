from django. urls import path
from .views import (
    DashboardStatsView,
    TopCitizensView,
    TopWorkersView,
    RecentActivitiesView,
    TrendDataView,
    StatusDistributionView,
    ZoneStatsView
)

urlpatterns = [
    # ✅ Remove 'dashboard/' prefix from each path
    path('stats/', DashboardStatsView. as_view(), name='dashboard-stats'),
    path('top-citizens/', TopCitizensView.as_view(), name='top-citizens'),
    path('top-workers/', TopWorkersView. as_view(), name='top-workers'),
    path('activities/', RecentActivitiesView. as_view(), name='recent-activities'),
    path('trends/', TrendDataView.as_view(), name='trend-data'),
    path('status-distribution/', StatusDistributionView.as_view(), name='status-distribution'),
    path('zone-stats/', ZoneStatsView.as_view(), name='zone-stats'),
]