from decimal import Decimal
from unittest.mock import patch

import pandas as pd
from django.test import TestCase

from .models import Trade


class TradingViewsTests(TestCase):
    def test_home_page_loads(self):
        """The home page should load successfully."""
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Paper Trading App')

    @patch('trading.views.yf.Ticker')
    def test_search_page_shows_price(self, mock_ticker):
        """Searching for a ticker should show the fetched price."""
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [123.45],
        })

        response = self.client.get('/search/', {'ticker': 'aapl'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You searched for: AAPL')
        self.assertContains(response, '123.45')

    @patch('trading.views.yf.Ticker')
    def test_buy_trade_saves(self, mock_ticker):
        """A valid buy trade should be saved to the database."""
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [250.00],
        })

        response = self.client.post('/trade/new/', {
            'ticker': 'MSFT',
            'trade_type': 'BUY',
            'quantity': '2',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trade.objects.count(), 1)
        trade = Trade.objects.first()
        self.assertEqual(trade.ticker, 'MSFT')
        self.assertEqual(trade.trade_type, 'BUY')
        self.assertEqual(trade.quantity, 2)
        self.assertEqual(trade.price, Decimal('250.00'))

    @patch('trading.views.yf.Ticker')
    def test_oversell_is_blocked(self, mock_ticker):
        """The app should block selling more shares than are owned."""
        Trade.objects.create(
            ticker='AAPL',
            trade_type='BUY',
            quantity=5,
            price=Decimal('100.00'),
        )
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [100.00],
        })

        response = self.client.post('/trade/new/', {
            'ticker': 'AAPL',
            'trade_type': 'SELL',
            'quantity': '10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You cannot sell more shares than you currently own.')
        self.assertEqual(Trade.objects.count(), 1)

    @patch('trading.views.yf.Ticker')
    def test_buy_is_blocked_when_cash_is_too_low(self, mock_ticker):
        """The app should block buys that cost more than the cash balance."""
        Trade.objects.create(
            ticker='AAPL',
            trade_type='BUY',
            quantity=90,
            price=Decimal('100.00'),
        )
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [200.00],
        })

        response = self.client.post('/trade/new/', {
            'ticker': 'NVDA',
            'trade_type': 'BUY',
            'quantity': '10',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You do not have enough cash to make that purchase.')
        self.assertEqual(Trade.objects.filter(ticker='NVDA').count(), 0)

    def test_clear_trades_removes_saved_data(self):
        """The clear trades button should delete all saved trades."""
        Trade.objects.create(
            ticker='SPY',
            trade_type='BUY',
            quantity=1,
            price=Decimal('500.00'),
        )

        response = self.client.post('/demo/clear/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trade.objects.count(), 0)
        self.assertContains(response, 'All trades were cleared successfully.')
