from django.contrib import admin
from .models import Report


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = [
        'report_id',
        'report_source',
        'citizen_id',
        'created_by_admin',
        'worker_id',
        'status',
        'waste_type',
        'ai_confidence',
        'submitted_at',
    ]
    list_filter = ['status', 'report_source', 'ai_result', 'waste_type', 'submitted_at']
    search_fields = [
        'report_id',
        'citizen_id__name',
        'citizen_id__email',
        'created_by_admin__name',
        'created_by_admin__email',
    ]
    readonly_fields = ['report_id', 'submitted_at']
    
    fieldsets = (
        ('Report Information', {
            'fields': ('report_id', 'report_source', 'citizen_id', 'created_by_admin', 'worker_id', 'status')
        }),
        ('AI Analysis', {
            'fields':  ('ai_result', 'waste_type', 'ai_confidence')
        }),
        ('Location', {
            'fields': ('gps_coords',)
        }),
        ('Images', {
            'fields': ('image_before', 'image_after')
        }),
        ('Timestamps', {
            'fields': ('submitted_at',)
        }),
    )