from django.contrib import admin
from . models import DownloadTicket

class DownloadTicketAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'video_url', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'created_at', 'updated_at')
    search_fields = ('id', 'user__username', 'video_url')
    readonly_fields = ('id', 'created_at', 'updated_at')
admin.site.register(DownloadTicket, DownloadTicketAdmin)
