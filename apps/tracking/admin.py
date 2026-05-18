from django.contrib import admin
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    """
    Admin interface for Activity Log
    Read-only view for security audit trail
    """
    
    # Display columns in list view
    list_display = [
        'log_id',
        'actor_type',
        'actor_id',
        'action',
        'target_type',
        'target_id',
        'created_at'
    ]
    
    # Filter options in sidebar
    list_filter = [
        'actor_type',
        'action',
        'target_type',
        'created_at'
    ]
    
    # Search functionality
    search_fields = [
        'description',
        'action',
        'actor_id',
        'target_id'
    ]
    
    # Read-only fields (all fields for audit logs)
    readonly_fields = [
        'log_id',
        'actor_type',
        'actor_id',
        'action',
        'target_type',
        'target_id',
        'description',
        'created_at'
    ]
    
    # Default ordering
    ordering = ['-created_at']
    
    # Pagination
    list_per_page = 50
    
    # Disable add permission - logs are auto-generated
    def has_add_permission(self, request):
        return False
    
    # Disable change permission - logs are immutable
    def has_change_permission(self, request, obj=None):
        return False
    
    # Disable delete permission - logs must be preserved
    def has_delete_permission(self, request, obj=None):
        return False
    
    # Custom display for better readability
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related()  # Optimize queries if needed