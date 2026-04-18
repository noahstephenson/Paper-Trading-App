"""
Pytest test suite for the paper trading app.

Covers two major standalone functions as unit tests:
  - fetch_latest_price(ticker): market data retrieval via yfinance
  - get_trade_balances(user, ticker, starting_cash): core portfolio accounting

Plus integration-level view tests for every major user flow.
"""

from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest
from django.contrib.auth import get_user_model

from .models import Trade
from .views import fetch_latest_price, get_trade_balances


# ── Fixtures ──────────────────────────────────────────────────────────────────
# Shared fixtures are injected by name into any test that lists them as params.

@pytest.fixture
def user(db):
    # A basic test user with no trades.
    return get_user_model().objects.create_user(username='trader1', password='testpass123')


@pytest.fixture
def other_user(db):
    # A second user used to verify data isolation between accounts.
    return get_user_model().objects.create_user(username='trader2', password='testpass123')


@pytest.fixture
def auth_client(client, user):
    # Django test client already logged in as `user`, skipping the login form.
    client.force_login(user)
    return client


# ── Unit tests: fetch_latest_price ────────────────────────────────────────────
# yfinance is mocked — these tests run offline and need no database.

@patch('trading.views.yf.Ticker')
def test_fetch_latest_price_returns_decimal_for_valid_ticker(mock_ticker):
    """A valid ticker should return a Decimal price rounded to two places."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.25]})

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


# ── Unit tests: get_trade_balances ────────────────────────────────────────────
# Pure DB logic — no external calls. Each test gets a fresh isolated database.

@pytest.mark.django_db
def test_get_trade_balances_fresh_account_has_full_cash(user):
    """A user with no trades should have the full starting cash and zero shares."""
    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('10000.00')
    assert shares == 0


@pytest.mark.django_db
def test_get_trade_balances_buy_reduces_cash_and_adds_shares(user):
    """Buying shares should reduce cash and increase the share count."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=5, price=Decimal('100.00'))

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('9500.00')   # 10000 - (5 * 100)
    assert shares == 5


@pytest.mark.django_db
def test_get_trade_balances_sell_restores_cash_and_removes_shares(user):
    """Selling shares should increase cash and decrease the share count."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=10, price=Decimal('100.00'))
    Trade.objects.create(user=user, ticker='AAPL', trade_type='SELL', quantity=3, price=Decimal('120.00'))

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('9360.00')   # 10000 - 1000 + 360
    assert shares == 7


@pytest.mark.django_db
def test_get_trade_balances_only_counts_shares_for_given_ticker(user):
    """Share count should only reflect the requested ticker, not others."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=3, price=Decimal('100.00'))
    Trade.objects.create(user=user, ticker='MSFT', trade_type='BUY', quantity=10, price=Decimal('50.00'))

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('9200.00')   # 10000 - 300 - 500
    assert shares == 3


@pytest.mark.django_db
def test_get_trade_balances_ignores_other_users_trades(user, other_user):
    """Balances must be isolated per user — another user's trades don't count."""
    Trade.objects.create(user=other_user, ticker='AAPL', trade_type='BUY', quantity=50, price=Decimal('100.00'))

    cash, shares = get_trade_balances(user, 'AAPL', Decimal('10000.00'))

    assert cash == Decimal('10000.00')
    assert shares == 0


# ── Home page ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_home_page_loads(client):
    """The home page should load successfully."""
    response = client.get('/')

    assert response.status_code == 200
    assert 'Paper Trading App' in response.content.decode()
    assert 'Create an Account' in response.content.decode()
    assert 'Log In to Start Trading' in response.content.decode()


@pytest.mark.django_db
def test_home_page_shows_summary_for_logged_in_user(auth_client):
    """The home page should show trading summary values after login."""
    response = auth_client.get('/')

    assert response.status_code == 200
    assert 'Starting Cash: $10000.00' in response.content.decode()
    assert 'Saved Trades: 0' in response.content.decode()
    assert 'Active Holdings: 0' in response.content.decode()


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_protected_pages_require_login(client):
    """Protected trading pages should redirect anonymous users to login."""
    for url in ['/search/', '/trade/new/', '/trades/', '/portfolio/']:
        response = client.get(url)
        assert response.status_code == 302
        assert '/accounts/login/' in response.url


@pytest.mark.django_db
def test_login_page_preserves_next_value(client):
    """The login page should keep the redirect target for protected pages."""
    response = client.get('/accounts/login/?next=/search/')

    assert response.status_code == 200
    assert 'name="next" value="/search/"' in response.content.decode()


@pytest.mark.django_db
def test_login_redirects_to_home_when_no_next(client, user):
    """Logging in without a next param should redirect to the home page."""
    response = client.post('/accounts/login/', {
        'username': 'trader1',
        'password': 'testpass123',
    }, follow=True)

    assert response.status_code == 200
    assert response.redirect_chain == [('/', 302)]


@pytest.mark.django_db
def test_accounts_root_redirects_to_login(client):
    """The accounts root URL should redirect to the login page."""
    response = client.get('/accounts/')

    assert response.status_code == 302
    assert response.url == '/accounts/login/'


@pytest.mark.django_db
def test_register_page_loads(client):
    """The register page should load successfully."""
    response = client.get('/accounts/register/')

    assert response.status_code == 200
    assert 'Create Account' in response.content.decode()


@pytest.mark.django_db
def test_register_creates_user_and_redirects_to_login(client):
    """Submitting the register form should create a new user."""
    response = client.post('/accounts/register/', {
        'username': 'newtrader',
        'password1': 'StrongPass123!',
        'password2': 'StrongPass123!',
    })

    assert response.status_code == 302
    assert response.url == '/accounts/login/?registered=1'
    assert get_user_model().objects.filter(username='newtrader').exists()


@pytest.mark.django_db
def test_logout_post_redirects_to_home(auth_client):
    """Logging out with POST should redirect to the home page."""
    response = auth_client.post('/accounts/logout/')

    assert response.status_code == 302
    assert response.url == '/'


# ── Search ────────────────────────────────────────────────────────────────────
# View tests use `with patch(...)` to replace yfinance so tests run offline.

@pytest.mark.django_db
def test_search_page_shows_price(auth_client):
    """Searching for a ticker should show the fetched price and details."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.info = {'shortName': 'Apple Inc.'}
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [120.00, 123.45],
            'High': [121.00, 125.00],
            'Low': [119.50, 122.00],
        })
        response = auth_client.get('/search/', {'ticker': 'aapl'})

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Apple Inc.' in body
    assert '123.45' in body
    assert 'Previous Close' in body
    assert '$120.00' in body
    assert '$125.00' in body
    assert '$122.00' in body
    assert '$3.45' in body
    assert '2.88%' in body
    assert 'Trade AAPL' in body


@pytest.mark.django_db
def test_search_shows_plotly_chart_for_valid_ticker(auth_client):
    """A valid ticker search should include a Plotly chart in the response."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.info = {'shortName': 'Apple Inc.'}
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            'Close': [120.00, 123.45],
            'High': [121.00, 125.00],
            'Low': [119.50, 122.00],
        })
        response = auth_client.get('/search/', {'ticker': 'AAPL'})

    assert response.status_code == 200
    assert 'plotly' in response.content.decode()


@pytest.mark.django_db
def test_search_shows_no_chart_for_invalid_ticker(auth_client):
    """An invalid ticker should not show a chart."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.info = {}
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        response = auth_client.get('/search/', {'ticker': 'ZZZZ'})

    assert response.status_code == 200
    assert 'plotly' not in response.content.decode()
    assert 'No stock data was found for that ticker.' in response.content.decode()


@pytest.mark.django_db
def test_search_whitespace_ticker_shows_error(auth_client):
    """A whitespace-only ticker should show a prompt, not crash."""
    response = auth_client.get('/search/', {'ticker': '   '})

    assert response.status_code == 200
    assert 'Please enter a ticker symbol.' in response.content.decode()


# ── Trade form ────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_trade_page_prefills_ticker_from_search_query(auth_client):
    """The trade form should prefill a ticker passed from the search page."""
    response = auth_client.get('/trade/new/?ticker=aapl')

    assert response.status_code == 200
    assert 'value="AAPL"' in response.content.decode()
    assert 'prefilled from your search' in response.content.decode()


@pytest.mark.django_db
def test_trade_page_reviews_price_before_confirmation(auth_client):
    """Submitting the form should show a confirmation step before saving."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [250.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'MSFT', 'trade_type': 'BUY', 'quantity': '2',
        })

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Review Trade Details' in body
    assert 'Check the price below, then save the trade if it looks right.' in body
    assert 'Current price: $250.00' in body
    assert 'Estimated total: $500.00' in body
    assert 'Save Trade' in body
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_buy_trade_saves(auth_client, user):
    """A submitted trade should save successfully after confirmation."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [250.00]})
        review_response = auth_client.post('/trade/new/', {
            'ticker': 'MSFT', 'trade_type': 'BUY', 'quantity': '2',
        })
        response = auth_client.post('/trade/new/', {'form_action': 'confirm'}, follow=True)

    assert review_response.status_code == 200
    assert 'Review Trade Details' in review_response.content.decode()
    assert response.status_code == 200
    assert response.redirect_chain == [('/trade/new/', 302)]
    assert Trade.objects.count() == 1
    trade = Trade.objects.first()
    assert trade.user == user
    assert trade.ticker == 'MSFT'
    assert trade.trade_type == 'BUY'
    assert trade.quantity == 2
    assert trade.price == Decimal('250.00')
    assert 'BUY trade confirmed for 2 shares of MSFT' in response.content.decode()


@pytest.mark.django_db
def test_confirm_trade_uses_reviewed_server_price(auth_client):
    """Confirmation should use the reviewed price stored on the server."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [250.00]})
        auth_client.post('/trade/new/', {'ticker': 'MSFT', 'trade_type': 'BUY', 'quantity': '2'})
        response = auth_client.post('/trade/new/', {
            'ticker': 'HACK', 'trade_type': 'SELL', 'quantity': '999',
            'quoted_price': '1.00', 'form_action': 'confirm',
        }, follow=True)

    assert response.status_code == 200
    assert Trade.objects.count() == 1
    trade = Trade.objects.first()
    assert trade.ticker == 'MSFT'
    assert trade.trade_type == 'BUY'
    assert trade.quantity == 2
    assert trade.price == Decimal('250.00')
    assert 'BUY trade confirmed for 2 shares of MSFT' in response.content.decode()


@pytest.mark.django_db
def test_confirm_without_pending_trade_shows_error(auth_client):
    """Hitting confirm with no pending session trade should show an error."""
    response = auth_client.post('/trade/new/', {'form_action': 'confirm'})

    assert response.status_code == 200
    assert 'Please submit the trade again before confirming it.' in response.content.decode()
    assert Trade.objects.count() == 0


# ── Trade validation ──────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_invalid_trade_type_is_blocked(auth_client):
    """The app should reject trade types outside BUY and SELL."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [250.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'MSFT', 'trade_type': 'HACK', 'quantity': '2',
        })

    assert response.status_code == 200
    assert 'Choose a valid trade type.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_oversell_is_blocked(auth_client, user):
    """The app should block selling more shares than are owned."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=5, price=Decimal('100.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'SELL', 'quantity': '10',
        })

    assert response.status_code == 200
    assert 'You cannot sell more shares than you currently own.' in response.content.decode()
    assert Trade.objects.count() == 1


@pytest.mark.django_db
def test_buy_is_blocked_when_cash_is_too_low(auth_client, user):
    """The app should block buys that cost more than the cash balance."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=90, price=Decimal('100.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [200.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'NVDA', 'trade_type': 'BUY', 'quantity': '10',
        })

    assert response.status_code == 200
    assert 'You do not have enough cash to make that purchase.' in response.content.decode()
    assert Trade.objects.filter(ticker='NVDA').count() == 0


@pytest.mark.django_db
def test_zero_quantity_is_blocked(auth_client):
    """The app should block trades with a quantity of zero."""
    response = auth_client.post('/trade/new/', {
        'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '0',
    })

    assert response.status_code == 200
    assert 'Quantity must be greater than zero.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_negative_quantity_is_blocked(auth_client):
    """The app should block trades with a negative quantity."""
    response = auth_client.post('/trade/new/', {
        'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '-5',
    })

    assert response.status_code == 200
    assert 'Quantity must be greater than zero.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_non_numeric_quantity_is_blocked(auth_client):
    """The app should block trades where quantity is not a number."""
    response = auth_client.post('/trade/new/', {
        'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': 'abc',
    })

    assert response.status_code == 200
    assert 'Enter a valid quantity.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_empty_ticker_is_blocked(auth_client):
    """The app should block a trade submission with no ticker."""
    response = auth_client.post('/trade/new/', {
        'ticker': '', 'trade_type': 'BUY', 'quantity': '5',
    })

    assert response.status_code == 200
    assert 'Please fill in every field.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_sell_validation_only_uses_logged_in_users_holdings(auth_client, other_user):
    """A user should not be able to sell another user's shares."""
    Trade.objects.create(user=other_user, ticker='AAPL', trade_type='BUY', quantity=5, price=Decimal('100.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'SELL', 'quantity': '1',
        })

    assert response.status_code == 200
    assert 'You cannot sell more shares than you currently own.' in response.content.decode()


# ── Trade history ─────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_trade_history_shows_formatted_date(auth_client, user):
    """The trade history page should show a readable trade date."""
    trade = Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=2, price=Decimal('100.00'))
    Trade.objects.filter(pk=trade.pk).update(
        created_at=datetime(2026, 3, 25, 14, 30, tzinfo=timezone.utc)
    )

    response = auth_client.get('/trades/')

    assert response.status_code == 200
    assert '$100.00' in response.content.decode()
    assert 'Mar 25, 2026 2:30 p.m.' in response.content.decode()


@pytest.mark.django_db
def test_trade_history_shows_trade_total(auth_client, user):
    """The trade history page should show the total cost for each trade."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=4, price=Decimal('150.00'))

    response = auth_client.get('/trades/')

    assert response.status_code == 200
    assert '$600.00' in response.content.decode()


@pytest.mark.django_db
def test_trade_history_only_shows_logged_in_users_trades(auth_client, user, other_user):
    """Trade history should only show trades for the logged-in user."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=1, price=Decimal('100.00'))
    Trade.objects.create(user=other_user, ticker='MSFT', trade_type='BUY', quantity=1, price=Decimal('200.00'))

    response = auth_client.get('/trades/')

    assert 'AAPL' in response.content.decode()
    assert 'MSFT' not in response.content.decode()


# ── Portfolio ─────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_portfolio_shows_average_cost_basis(auth_client, user):
    """The portfolio page should show the weighted average cost per share."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=2, price=Decimal('100.00'))
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=1, price=Decimal('160.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
        response = auth_client.get('/portfolio/')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'AAPL' in body
    assert '<td>3</td>' in body
    assert '$120.00' in body
    assert '$150.00' in body
    assert '$450.00' in body


@pytest.mark.django_db
def test_portfolio_shows_gain_metrics(auth_client, user):
    """The portfolio page should show total, per-share, and percent gain."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=2, price=Decimal('100.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [125.00]})
        response = auth_client.get('/portfolio/')

    assert response.status_code == 200
    body = response.content.decode()
    assert '$250.00' in body
    assert '$50.00' in body
    assert '$25.00' in body
    assert '25.00%' in body


@pytest.mark.django_db
def test_portfolio_excludes_fully_sold_holdings(auth_client, user):
    """A ticker where all shares were sold should not appear in the portfolio."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=3, price=Decimal('100.00'))
    Trade.objects.create(user=user, ticker='AAPL', trade_type='SELL', quantity=3, price=Decimal('110.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [115.00]})
        response = auth_client.get('/portfolio/')

    assert response.status_code == 200
    assert 'AAPL' not in response.content.decode()
    assert 'No holdings to show yet.' in response.content.decode()


@pytest.mark.django_db
def test_portfolio_only_shows_current_users_holdings(auth_client, other_user):
    """Another user's trades should not appear in the portfolio."""
    Trade.objects.create(user=other_user, ticker='MSFT', trade_type='BUY', quantity=5, price=Decimal('200.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [210.00]})
        response = auth_client.get('/portfolio/')

    assert response.status_code == 200
    assert 'MSFT' not in response.content.decode()
    assert 'No holdings to show yet.' in response.content.decode()


# ── Demo ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_clear_trades_removes_saved_data(auth_client, user, other_user):
    """The clear trades action should only delete the logged-in user's trades."""
    Trade.objects.create(user=user, ticker='SPY', trade_type='BUY', quantity=1, price=Decimal('500.00'))
    Trade.objects.create(user=other_user, ticker='AAPL', trade_type='BUY', quantity=1, price=Decimal('200.00'))

    response = auth_client.post('/demo/clear/', follow=True)

    assert response.status_code == 200
    assert Trade.objects.filter(user=user).count() == 0
    assert Trade.objects.filter(user=other_user).count() == 1
    assert 'All trades were cleared successfully.' in response.content.decode()
