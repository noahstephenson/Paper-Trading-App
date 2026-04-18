"""
Pytest unit tests for two major functions in the paper trading app.

Function 1: fetch_latest_price(ticker)
    Retrieves the latest closing price from yfinance.
    Called on every trade review — the whole trade flow depends on it.

Function 2: get_trade_balances(user, ticker, starting_cash)
    Computes a user's cash balance and share count from their trade history.
    Called on every buy/sell to validate the trade before saving.
"""

from decimal import Decimal
from unittest.mock import patch

import pandas as pd
import pytest
from django.contrib.auth import get_user_model

from .models import Trade
from .views import fetch_latest_price, get_trade_balances


# ── Function 1: fetch_latest_price ───────────────────────────────────────────
# No database needed — yfinance is mocked so the tests run offline.

@patch('trading.views.yf.Ticker')
def test_fetch_latest_price_returns_decimal_for_valid_ticker(mock_ticker):
    """A valid ticker should return a Decimal price rounded to two places."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({
        'Close': [150.25],
    })

    price = fetch_latest_price('AAPL')

    assert price == Decimal('150.25')
    assert isinstance(price, Decimal)


@patch('trading.views.yf.Ticker')
def test_fetch_latest_price_returns_none_when_no_data(mock_ticker):
    """An invalid ticker with no history data should return None, not crash."""
    mock_ticker.return_value.history.return_value = pd.DataFrame()

    price = fetch_latest_price('ZZZZ')

    assert price is None


@patch('trading.views.yf.Ticker')
def test_fetch_latest_price_uses_most_recent_close(mock_ticker):
    """When multiple rows exist, the last closing price should be returned."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({
        'Close': [100.00, 110.00, 125.50],
    })

    price = fetch_latest_price('MSFT')

    assert price == Decimal('125.50')


# ── Function 2: get_trade_balances ───────────────────────────────────────────
# Reads from the database — each test gets a fresh isolated DB via django_db.

@pytest.mark.django_db
def test_get_trade_balances_fresh_account_has_full_cash():
    """A user with no trades should have the full starting cash and zero shares."""
    user = get_user_model().objects.create_user(username='u1', password='pass')

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('10000.00')
    assert shares == 0


@pytest.mark.django_db
def test_get_trade_balances_buy_reduces_cash_and_adds_shares():
    """Buying shares should reduce cash and increase the share count."""
    user = get_user_model().objects.create_user(username='u2', password='pass')
    Trade.objects.create(
        user=user, ticker='AAPL', trade_type='BUY', quantity=5, price=Decimal('100.00')
    )

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('9500.00')   # 10000 - (5 * 100)
    assert shares == 5


@pytest.mark.django_db
def test_get_trade_balances_sell_restores_cash_and_removes_shares():
    """Selling shares should increase cash and decrease the share count."""
    user = get_user_model().objects.create_user(username='u3', password='pass')
    Trade.objects.create(
        user=user, ticker='AAPL', trade_type='BUY', quantity=10, price=Decimal('100.00')
    )
    Trade.objects.create(
        user=user, ticker='AAPL', trade_type='SELL', quantity=3, price=Decimal('120.00')
    )

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('9360.00')   # 10000 - 1000 + 360
    assert shares == 7


@pytest.mark.django_db
def test_get_trade_balances_only_counts_shares_for_given_ticker():
    """Share count should only reflect the requested ticker, not others."""
    user = get_user_model().objects.create_user(username='u4', password='pass')
    Trade.objects.create(
        user=user, ticker='AAPL', trade_type='BUY', quantity=3, price=Decimal('100.00')
    )
    Trade.objects.create(
        user=user, ticker='MSFT', trade_type='BUY', quantity=10, price=Decimal('50.00')
    )

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    # Cash is reduced by both trades, but shares only count AAPL
    assert cash == Decimal('9200.00')   # 10000 - 300 - 500
    assert shares == 3


@pytest.mark.django_db
def test_get_trade_balances_ignores_other_users_trades():
    """Balances must be isolated per user — another user's trades don't count."""
    User = get_user_model()
    user = User.objects.create_user(username='u5', password='pass')
    other = User.objects.create_user(username='u6', password='pass')
    Trade.objects.create(
        user=other, ticker='AAPL', trade_type='BUY', quantity=50, price=Decimal('100.00')
    )

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('10000.00')
    assert shares == 0
