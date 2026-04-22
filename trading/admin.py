from django.contrib import admin
from .models import Trade


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    # Show the main trade fields directly in the admin list page.
    list_display = ('user', 'ticker', 'trade_type', 'quantity', 'price', 'created_at', 'short_notes')
    list_filter = ('user', 'trade_type', 'ticker')
    search_fields = ('ticker', 'user__username')
    ordering = ('-created_at',)

    def short_notes(self, obj):
        return obj.notes[:60] + '…' if len(obj.notes) > 60 else obj.notes
    short_notes.short_description = 'Notes'
