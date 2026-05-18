from django.contrib import admin
from .models import Admin

@admin.register(Admin)
class AdminModelAdmin(admin.ModelAdmin):
    list_display = ['admin_id', 'email', 'name', 'created_at', 'last_login']
    search_fields = ['email', 'name']