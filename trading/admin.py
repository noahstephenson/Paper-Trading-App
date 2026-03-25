from django.contrib import admin
from .models import Trade


# Register Trade so we can view and add trades in the Django admin site.
admin.site.register(Trade)
