from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Trade


class TradingViewsTests(TestCase):
    def setUp(self):
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(
            username='trader1',
            password='testpass123',
        )
        self.other_user = self.user_model.objects.create_user(
            username='trader2',
            password='testpass123',
        )

    def test_home_page_loads(self):
        """The home page should load successfully."""
        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Paper Trading App')
        self.assertContains(response, 'Create an Account')
        self.assertContains(response, 'Log In to Start Trading')

    def test_home_page_shows_summary_for_logged_in_user(self):
        """The home page should show trading summary values after login."""
        self.client.force_login(self.user)

        response = self.client.get('/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Starting Cash: $10000.00')
        self.assertContains(response, 'Saved Trades: 0')
        self.assertContains(response, 'Active Holdings: 0')

    def test_protected_pages_require_login(self):
        """Protected trading pages should redirect anonymous users to login."""
        protected_urls = ['/search/', '/trade/new/', '/trades/', '/portfolio/']

        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn('/accounts/login/', response.url)

    def test_login_page_preserves_next_value(self):
        """The login page should keep the redirect target for protected pages."""
        response = self.client.get('/accounts/login/?next=/search/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="next" value="/search/"', html=False)

    def test_accounts_root_redirects_to_login(self):
        """The accounts root URL should redirect to the login page."""
        response = self.client.get('/accounts/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/accounts/login/')

    def test_register_page_loads(self):
        """The register page should load successfully."""
        response = self.client.get('/accounts/register/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Account')

    def test_register_creates_user_and_redirects_to_login(self):
        """Submitting the register form should create a new user."""
        response = self.client.post('/accounts/register/', {
            'username': 'newtrader',
            'password1': 'StrongPass123!',
            'password2': 'StrongPass123!',
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/accounts/login/?registered=1')
        self.assertTrue(self.user_model.objects.filter(username='newtrader').exists())

    def test_logout_post_redirects_to_home(self):
        """Logging out with POST should redirect to the home page."""
        self.client.force_login(self.user)

        response = self.client.post('/accounts/logout/')

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/')

    @patch('trading.views.yf.Ticker')
    def test_search_page_shows_price(self, mock_ticker):
        """Searching for a ticker should show the fetched price."""
        self.client.force_login(self.user)
        mock_ticker.return_value.info = {
            'shortName': 'Apple Inc.',
        }
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [120.00, 123.45],
            'High': [121.00, 125.00],
            'Low': [119.50, 122.00],
        })

        response = self.client.get('/search/', {'ticker': 'aapl'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apple Inc.')
        self.assertContains(response, '123.45')
        self.assertContains(response, 'Previous Close')
        self.assertContains(response, '$120.00')
        self.assertContains(response, '$125.00')
        self.assertContains(response, '$122.00')
        self.assertContains(response, '$3.45')
        self.assertContains(response, '2.88%')
        self.assertContains(response, 'Trade AAPL')

    def test_trade_page_prefills_ticker_from_search_query(self):
        """The trade form should prefill a ticker passed from the search page."""
        self.client.force_login(self.user)

        response = self.client.get('/trade/new/?ticker=aapl')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="AAPL"', html=False)
        self.assertContains(response, 'prefilled from your search')

    @patch('trading.views.yf.Ticker')
    def test_buy_trade_saves(self, mock_ticker):
        """A submitted trade should save successfully after confirmation."""
        self.client.force_login(self.user)
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [250.00],
        })

        review_response = self.client.post('/trade/new/', {
            'ticker': 'MSFT',
            'trade_type': 'BUY',
            'quantity': '2',
        })
        response = self.client.post('/trade/new/', {
            'form_action': 'confirm',
        }, follow=True)

        self.assertEqual(review_response.status_code, 200)
        self.assertContains(review_response, 'Review Trade Details')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain, [('/trade/new/', 302)])
        self.assertEqual(Trade.objects.count(), 1)
        trade = Trade.objects.first()
        self.assertEqual(trade.user, self.user)
        self.assertEqual(trade.ticker, 'MSFT')
        self.assertEqual(trade.trade_type, 'BUY')
        self.assertEqual(trade.quantity, 2)
        self.assertEqual(trade.price, Decimal('250.00'))
        self.assertContains(response, 'BUY trade confirmed for 2 shares of MSFT')

    @patch('trading.views.yf.Ticker')
    def test_trade_page_reviews_price_before_confirmation(self, mock_ticker):
        """Submitting the form should show a confirmation step before saving."""
        self.client.force_login(self.user)
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [250.00],
        })

        response = self.client.post('/trade/new/', {
            'ticker': 'MSFT',
            'trade_type': 'BUY',
            'quantity': '2',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Review Trade Details')
        self.assertContains(response, 'Check the price below, then save the trade if it looks right.')
        self.assertContains(response, 'Current price: $250.00')
        self.assertContains(response, 'Estimated total: $500.00')
        self.assertContains(response, 'Save Trade')
        self.assertEqual(Trade.objects.count(), 0)

    @patch('trading.views.yf.Ticker')
    def test_confirm_trade_uses_reviewed_server_price(self, mock_ticker):
        """Confirmation should use the reviewed price stored on the server."""
        self.client.force_login(self.user)
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [250.00],
        })

        self.client.post('/trade/new/', {
            'ticker': 'MSFT',
            'trade_type': 'BUY',
            'quantity': '2',
        })
        response = self.client.post('/trade/new/', {
            'ticker': 'HACK',
            'trade_type': 'SELL',
            'quantity': '999',
            'quoted_price': '1.00',
            'form_action': 'confirm',
        }, follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trade.objects.count(), 1)
        trade = Trade.objects.first()
        self.assertEqual(trade.ticker, 'MSFT')
        self.assertEqual(trade.trade_type, 'BUY')
        self.assertEqual(trade.quantity, 2)
        self.assertEqual(trade.price, Decimal('250.00'))
        self.assertContains(response, 'BUY trade confirmed for 2 shares of MSFT')

    @patch('trading.views.yf.Ticker')
    def test_invalid_trade_type_is_blocked(self, mock_ticker):
        """The app should reject trade types outside BUY and SELL."""
        self.client.force_login(self.user)
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [250.00],
        })

        response = self.client.post('/trade/new/', {
            'ticker': 'MSFT',
            'trade_type': 'HACK',
            'quantity': '2',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose a valid trade type.')
        self.assertEqual(Trade.objects.count(), 0)

    @patch('trading.views.yf.Ticker')
    def test_oversell_is_blocked(self, mock_ticker):
        """The app should block selling more shares than are owned."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
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
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
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
        """The clear trades button should only delete the logged-in user's trades."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
            ticker='SPY',
            trade_type='BUY',
            quantity=1,
            price=Decimal('500.00'),
        )
        Trade.objects.create(
            user=self.other_user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=1,
            price=Decimal('200.00'),
        )

        response = self.client.post('/demo/clear/', follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trade.objects.filter(user=self.user).count(), 0)
        self.assertEqual(Trade.objects.filter(user=self.other_user).count(), 1)
        self.assertContains(response, 'All trades were cleared successfully.')

    @patch('trading.views.yf.Ticker')
    def test_portfolio_shows_average_cost_basis(self, mock_ticker):
        """The portfolio page should show the weighted average cost per share."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=2,
            price=Decimal('100.00'),
        )
        Trade.objects.create(
            user=self.user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=1,
            price=Decimal('160.00'),
        )
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [150.00],
        })

        response = self.client.get('/portfolio/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'AAPL')
        self.assertContains(response, '<td>3</td>', html=True)
        self.assertContains(response, '$120.00')
        self.assertContains(response, '$150.00')
        self.assertContains(response, '$450.00')

    def test_trade_history_shows_formatted_date(self):
        """The trade history page should show a readable trade date."""
        self.client.force_login(self.user)
        trade = Trade.objects.create(
            user=self.user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=2,
            price=Decimal('100.00'),
        )
        Trade.objects.filter(pk=trade.pk).update(
            created_at=datetime(2026, 3, 25, 14, 30, tzinfo=timezone.utc)
        )

        response = self.client.get('/trades/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '$100.00')
        self.assertContains(response, 'Mar 25, 2026 2:30 p.m.')

    @patch('trading.views.yf.Ticker')
    def test_portfolio_shows_gain_metrics(self, mock_ticker):
        """The portfolio page should show total, per-share, and percent gain."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=2,
            price=Decimal('100.00'),
        )
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [125.00],
        })

        response = self.client.get('/portfolio/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '$250.00')
        self.assertContains(response, '$50.00')
        self.assertContains(response, '$25.00')
        self.assertContains(response, '25.00%')

    @patch('trading.views.yf.Ticker')
    def test_sell_validation_only_uses_logged_in_users_holdings(self, mock_ticker):
        """A user should not be able to sell another user's shares."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.other_user,
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
            'quantity': '1',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'You cannot sell more shares than you currently own.')
        self.assertEqual(Trade.objects.filter(user=self.user).count(), 0)

    def test_trade_history_only_shows_logged_in_users_trades(self):
        """Trade history should only show trades for the logged-in user."""
        self.client.force_login(self.user)
        Trade.objects.create(
            user=self.user,
            ticker='AAPL',
            trade_type='BUY',
            quantity=1,
            price=Decimal('100.00'),
        )
        Trade.objects.create(
            user=self.other_user,
            ticker='MSFT',
            trade_type='BUY',
            quantity=1,
            price=Decimal('200.00'),
        )

        response = self.client.get('/trades/')

        self.assertContains(response, 'AAPL')
        self.assertNotContains(response, 'MSFT')
