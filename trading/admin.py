from django.contrib import admin
from .models import Trade


@admin.register(Trade)
class TradeAdmin(admin.ModelAdmin):
    # Show the main trade fields directly in the admin list page.
    list_display = ('ticker', 'trade_type', 'quantity', 'price', 'created_at')
    list_filter = ('trade_type', 'ticker')
    search_fields = ('ticker',)
    ordering = ('-created_at',)
