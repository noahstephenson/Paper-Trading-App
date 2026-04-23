from django.urls import path
from . import views

app_name = 'trading'

urlpatterns = [
    path('', views.index, name='index'),
    path('search/', views.search, name='search'),
    path('stock/<str:ticker>/', views.stock_detail, name='stock_detail'),
    path('trade/new/', views.create_trade, name='create_trade'),
    path('trades/', views.trade_history, name='trade_history'),
    path('portfolio/', views.portfolio, name='portfolio'),
    path('portfolio/coach/', views.coach_analysis_view, name='coach_analysis'),
    path('watchlist/', views.watchlist, name='watchlist'),
    path('watchlist/remove/<str:ticker>/', views.remove_from_watchlist, name='remove_from_watchlist'),
    path('demo/clear/', views.clear_trades, name='clear_trades'),
]
