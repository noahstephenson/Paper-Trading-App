from django.urls import path
from . import views

app_name = 'trading'

urlpatterns = [
    path('', views.index, name='index'),
    path('search/', views.search, name='search'),
    path('trade/new/', views.create_trade, name='create_trade'),
    path('trades/', views.trade_history, name='trade_history'),
    path('portfolio/', views.portfolio, name='portfolio'),
]
