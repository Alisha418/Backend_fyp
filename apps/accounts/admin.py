from django.contrib import admin
from . models import Account

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ['account_id', 'email', 'name', 'role', 'created_at']
    list_filter = ['role', 'created_at']
    search_fields = ['email', 'name']