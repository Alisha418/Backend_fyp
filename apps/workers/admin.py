from django.contrib import admin
from .models import Worker, WorkerLocation, WorkerMonthlyStats


@admin.register(Worker)
class WorkerAdmin(admin.ModelAdmin):
    list_display = [
        'employee_code',
        'get_name',
        'get_email',
        'total_tasks',
        'avg_rating',
        'is_tracking',
        'worker_active',
    ]

    list_filter = [
        'is_tracking',
        'created_at',
    ]

    search_fields = [
        'employee_code',
        'worker_id__name',
        'worker_id__email',
    ]

    readonly_fields = [
        'created_at',
        'updated_at',
        'total_tasks',
        'avg_rating',
    ]

    def get_name(self, obj):
        return obj.worker_id.name
    get_name.short_description = 'Name'

    def get_email(self, obj):
        return obj.worker_id.email
    get_email.short_description = 'Email'

    def worker_active(self, obj):
        return obj.worker_id.is_active
    worker_active.boolean = True
    worker_active.short_description = 'Active'


@admin.register(WorkerLocation)
class WorkerLocationAdmin(admin.ModelAdmin):
    list_display = [
        'worker_id',
        'latitude',
        'longitude',
        'recorded_at',
    ]

    list_filter = [
        'recorded_at',
    ]

    search_fields = [
        'worker_id__employee_code',
        'worker_id__worker_id__name',
    ]

    readonly_fields = [
        'recorded_at',
    ]


@admin.register(WorkerMonthlyStats)
class WorkerMonthlyStatsAdmin(admin.ModelAdmin):
    list_display = [
        'worker_id',
        'month',
        'resolved_tasks',
        'avg_rating',
        'badge',
        'monthly_rank',
    ]

    list_filter = [
        'month',
        'badge',
    ]

    search_fields = [
        'worker_id__employee_code',
        'worker_id__worker_id__name',
    ]
