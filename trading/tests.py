"""
Pytest test suite for the paper trading app.

Covers two major standalone functions as unit tests:
  - fetch_latest_price(ticker): market data retrieval via yfinance
  - get_trade_balances(user, ticker, starting_cash): core portfolio accounting

Plus integration-level view tests for every major user flow.
"""

from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache

from .models import Trade, UserProfile, WatchlistItem, CoachAnalysis
from .views import fetch_latest_price, get_trade_balances
from .services.ai_coach import build_portfolio_context, get_coach_analysis
from .services.formatting import format_large_number
from .services.market_data import get_stock_history, get_stock_info


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


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


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
    """The home page should show the dashboard summary cards after login."""
    response = auth_client.get('/')

    assert response.status_code == 200
    assert 'Dashboard' in response.content.decode()
    assert 'Total Portfolio Value' in response.content.decode()
    assert 'Cash Balance' in response.content.decode()


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
    mock_df = pd.DataFrame(
        {
            'Close': [120.00, 123.45],
            'High': [121.00, 125.00],
            'Low': [119.50, 122.00],
            'Open': [119.00, 121.00],
            'Volume': [1_000_000, 1_200_000],
        },
        index=pd.date_range('2024-01-01', periods=2),
    )
    with patch('trading.services.market_data.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.info = {'shortName': 'Apple Inc.'}
        mock_ticker.return_value.news = []
        mock_ticker.return_value.history.return_value = mock_df
        response = auth_client.get('/search/', {'ticker': 'aapl'})

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Apple Inc.' in body
    assert '123.45' in body
    assert 'Prev Close' in body
    assert '$120.00' in body
    assert '$125.00' in body
    assert '$122.00' in body
    assert '$3.45' in body
    assert '2.88%' in body
    assert 'Buy / Sell AAPL' in body


@pytest.mark.django_db
def test_search_shows_plotly_chart_for_valid_ticker(auth_client):
    """A valid ticker search should include a Plotly chart in the response."""
    mock_df = pd.DataFrame(
        {
            'Close': [120.00 + i for i in range(50)],
            'High':  [121.00 + i for i in range(50)],
            'Low':   [119.00 + i for i in range(50)],
            'Open':  [119.50 + i for i in range(50)],
            'Volume': [1_000_000] * 50,
        },
        index=pd.date_range('2023-01-01', periods=50),
    )
    with patch('trading.services.market_data.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.info = {'shortName': 'Apple Inc.'}
        mock_ticker.return_value.news = []
        mock_ticker.return_value.history.return_value = mock_df
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
    assert 'Confirm Trade' in body
    assert '$250.00' in body
    assert '$500.00' in body
    assert 'Confirm' in body
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
    assert 'Confirm Trade' in review_response.content.decode()
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
    user.profile.cash_balance = Decimal('1000.00')
    user.profile.save()
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [200.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'NVDA', 'trade_type': 'BUY', 'quantity': '10',
        })

    assert response.status_code == 200
    assert 'Insufficient funds' in response.content.decode()
    assert Trade.objects.filter(ticker='NVDA').count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("qty", ['0', '-5'])
def test_non_positive_quantity_is_blocked(auth_client, qty):
    """The app should block trades with a zero or negative quantity."""
    response = auth_client.post('/trade/new/', {
        'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': qty,
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


# ── Watchlist tests ───────────────────────────────────────────────────────────

@pytest.mark.django_db
def test_watchlist_page_loads(auth_client):
    """The watchlist page should return 200 for a logged-in user."""
    response = auth_client.get('/watchlist/')
    assert response.status_code == 200


@pytest.mark.django_db
def test_add_ticker_to_watchlist(auth_client, user):
    """POSTing a ticker to the watchlist page should save it for that user."""
    auth_client.post('/watchlist/', {'ticker': 'AAPL'})
    assert WatchlistItem.objects.filter(user=user, ticker='AAPL').exists()


@pytest.mark.django_db
def test_duplicate_ticker_not_added_twice(auth_client, user):
    """Adding the same ticker twice should result in only one watchlist entry."""
    auth_client.post('/watchlist/', {'ticker': 'AAPL'})
    auth_client.post('/watchlist/', {'ticker': 'AAPL'})
    assert WatchlistItem.objects.filter(user=user, ticker='AAPL').count() == 1


@pytest.mark.django_db
def test_remove_ticker_from_watchlist(auth_client, user):
    """POSTing to the remove URL should delete that ticker from the watchlist."""
    WatchlistItem.objects.create(user=user, ticker='TSLA')
    auth_client.post('/watchlist/remove/TSLA/')
    assert not WatchlistItem.objects.filter(user=user, ticker='TSLA').exists()


@pytest.mark.django_db
def test_watchlist_unauthenticated_redirects(client):
    """An unauthenticated request to the watchlist page should redirect to login."""
    response = client.get('/watchlist/')
    assert response.status_code == 302


@pytest.mark.django_db
def test_ticker_normalized_to_uppercase(auth_client, user):
    """Lowercase ticker input should be stored as uppercase."""
    auth_client.post('/watchlist/', {'ticker': 'aapl'})
    assert WatchlistItem.objects.filter(user=user, ticker='AAPL').exists()


@pytest.mark.django_db
def test_watchlist_user_isolation(auth_client, user, other_user):
    """The watchlist page should only show tickers belonging to the logged-in user."""
    WatchlistItem.objects.create(user=other_user, ticker='MSFT')
    response = auth_client.get('/watchlist/')
    assert 'MSFT' not in response.content.decode()


@pytest.mark.django_db
def test_watchlist_remove_only_own_tickers(auth_client, user, other_user):
    """A user's remove action should not affect another user's watchlist entries."""
    WatchlistItem.objects.create(user=other_user, ticker='GOOG')
    auth_client.post('/watchlist/remove/GOOG/')
    assert WatchlistItem.objects.filter(user=other_user, ticker='GOOG').exists()


# ── Auth: registration edge cases ─────────────────────────────────────────────

@pytest.mark.django_db
@pytest.mark.parametrize("username,pw1,pw2", [
    ('newuser',   'StrongPass123!', 'DifferentPass456!'),  # mismatched passwords
    ('newuser',   'abc',            'abc'),                # too short
    ('newuser',   'password123',    'password123'),        # common password
    ('newuser',   '12345678',       '12345678'),           # numeric only
    ('',          'StrongPass123!', 'StrongPass123!'),     # empty username
    ('johndoe99', 'johndoe99',      'johndoe99'),          # password similar to username
])
def test_register_rejects_invalid_input(client, username, pw1, pw2):
    """Invalid registration inputs should re-render the form without creating a user."""
    response = client.post('/accounts/register/', {
        'username': username, 'password1': pw1, 'password2': pw2,
    })
    assert response.status_code == 200
    assert not get_user_model().objects.filter(username=username).exists()


@pytest.mark.django_db
def test_register_shows_error_for_duplicate_username(client):
    """Registering with an already-taken username should fail."""
    get_user_model().objects.create_user(username='taken', password='StrongPass123!')

    response = client.post('/accounts/register/', {
        'username': 'taken',
        'password1': 'StrongPass123!',
        'password2': 'StrongPass123!',
    })

    assert response.status_code == 200
    assert get_user_model().objects.filter(username='taken').count() == 1


@pytest.mark.django_db
def test_register_redirects_already_logged_in_user(auth_client):
    """A logged-in user visiting the register page should be redirected to home."""
    response = auth_client.get('/accounts/register/')

    assert response.status_code == 302
    assert response.url == '/'


@pytest.mark.django_db
def test_login_shows_error_for_wrong_password(client, user):
    """Logging in with the wrong password should re-render the form with an error."""
    response = client.post('/accounts/login/', {
        'username': 'trader1',
        'password': 'wrongpassword',
    })

    assert response.status_code == 200
    body = response.content.decode()
    assert 'did not match' in body


@pytest.mark.django_db
def test_login_shows_error_for_nonexistent_user(client):
    """Logging in with a username that doesn't exist should show an error."""
    response = client.post('/accounts/login/', {
        'username': 'ghost',
        'password': 'StrongPass123!',
    })

    assert response.status_code == 200
    body = response.content.decode()
    assert 'did not match' in body


@pytest.mark.django_db
def test_full_register_login_and_portfolio_flow(client):
    """A new user can register, log in, and reach their empty portfolio."""
    # Register
    reg = client.post('/accounts/register/', {
        'username': 'brandnew',
        'password1': 'StrongPass123!',
        'password2': 'StrongPass123!',
    })
    assert reg.status_code == 302
    assert get_user_model().objects.filter(username='brandnew').exists()

    # Log in
    login = client.post('/accounts/login/', {
        'username': 'brandnew',
        'password': 'StrongPass123!',
    })
    assert login.status_code == 302

    # View portfolio
    portfolio = client.get('/portfolio/')
    assert portfolio.status_code == 200
    assert 'No holdings to show yet.' in portfolio.content.decode()


# ── New tests: 5 requested scenarios ─────────────────────────────────────────
# These expand coverage for: valid buy, oversell, invalid ticker on trade form,
# unauthenticated redirects, and the two-step confirmation flow.


# (1) Buying a valid ticker ────────────────────────────────────────────────────

@pytest.mark.django_db
def test_buy_valid_ticker_appears_in_trade_history(auth_client, user):
    """After a confirmed buy, the trade should appear in the history view with correct values."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '3'})
        auth_client.post('/trade/new/', {'form_action': 'confirm'})

    response = auth_client.get('/trades/')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'AAPL' in body
    assert 'BUY' in body
    assert '$100.00' in body
    assert '$300.00' in body   # 3 shares × $100 total


# (2) Selling more shares than owned ──────────────────────────────────────────

@pytest.mark.django_db
def test_oversell_blocked_at_confirm_step(auth_client, user):
    """If shares are sold between review and confirm, the confirm step should also block the oversell."""
    # User buys 2 shares
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=2, price=Decimal('100.00'))

    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        # Review a sell of 2 — valid at this moment, so pending_trade is stored in session
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'SELL', 'quantity': '2'})

    # Simulate those shares disappearing before the user clicks Confirm
    Trade.objects.create(user=user, ticker='AAPL', trade_type='SELL', quantity=2, price=Decimal('100.00'))

    # Confirm should now fail: 0 shares owned, pending trade wants to sell 2
    response = auth_client.post('/trade/new/', {'form_action': 'confirm'})

    assert response.status_code == 200
    assert 'You cannot sell more shares than you currently own.' in response.content.decode()
    # Only the manually created SELL exists — the pending one was not saved
    assert Trade.objects.filter(trade_type='SELL').count() == 1


# (3) Invalid ticker on the trade form ────────────────────────────────────────

@pytest.mark.django_db
def test_invalid_ticker_on_trade_form_shows_error(auth_client):
    """A ticker with no yfinance data should show a clear error on the trade form, not crash."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame()   # empty = no data
        response = auth_client.post('/trade/new/', {
            'ticker': 'ZZZZ', 'trade_type': 'BUY', 'quantity': '1',
        })

    assert response.status_code == 200
    assert 'Could not fetch a current price for that ticker.' in response.content.decode()
    assert Trade.objects.count() == 0


# (4) Unauthenticated redirects include ?next= ────────────────────────────────

@pytest.mark.django_db
def test_unauthenticated_redirects_include_next_url(client):
    """Login redirects must carry ?next= so the user lands on the right page after logging in."""
    for url in ['/portfolio/', '/trade/new/', '/trades/']:
        response = client.get(url)
        assert response.status_code == 302
        assert '/accounts/login/' in response.url
        assert f'next={url}' in response.url


# (5) Two-step confirmation flow ──────────────────────────────────────────────

@pytest.mark.django_db
def test_get_request_to_trade_form_clears_stale_pending_trade(auth_client):
    """A GET to the trade form should clear any pending trade so old sessions can't be confirmed."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        # Create a pending trade in the session via POST
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '2'})

    # GET request should wipe the pending trade
    auth_client.get('/trade/new/')

    # Confirm should now fail — session has been cleared
    response = auth_client.post('/trade/new/', {'form_action': 'confirm'})

    assert response.status_code == 200
    assert 'Please submit the trade again before confirming it.' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_sell_owned_shares_completes_two_step_flow(auth_client, user):
    """A user with shares should complete the full review → confirm sell flow successfully."""
    Trade.objects.create(user=user, ticker='TSLA', trade_type='BUY', quantity=5, price=Decimal('200.00'))

    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [220.00]})
        # Step 1: review
        review = auth_client.post('/trade/new/', {
            'ticker': 'TSLA', 'trade_type': 'SELL', 'quantity': '3',
        })
        review_body = review.content.decode()
        assert 'Confirm Trade' in review_body
        assert '$220.00' in review_body
        assert '$660.00' in review_body

        # Step 2: confirm
        confirm = auth_client.post('/trade/new/', {'form_action': 'confirm'}, follow=True)

    assert confirm.status_code == 200
    assert Trade.objects.filter(trade_type='SELL').count() == 1
    sell = Trade.objects.get(trade_type='SELL')
    assert sell.ticker == 'TSLA'
    assert sell.quantity == 3
    assert sell.price == Decimal('220.00')


# ── Trade Rationale Journal ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_trade_notes_saved_through_two_step_flow(auth_client):
    """Notes entered on the trade form should be saved to the Trade record."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
        auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '1',
            'notes': 'Strong earnings, bullish on AI segment.',
        })
        auth_client.post('/trade/new/', {'form_action': 'confirm'})

    trade = Trade.objects.get(ticker='AAPL')
    assert trade.notes == 'Strong earnings, bullish on AI segment.'


@pytest.mark.django_db
def test_trade_without_notes_still_works(auth_client):
    """Omitting the notes field should not break the trade flow; notes should be empty."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
        auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '1',
        })
        auth_client.post('/trade/new/', {'form_action': 'confirm'})

    trade = Trade.objects.get(ticker='AAPL')
    assert trade.notes == ''


@pytest.mark.django_db
def test_notes_appear_in_trade_history(auth_client, user):
    """A trade saved with notes should display those notes on the history page."""
    Trade.objects.create(
        user=user, ticker='MSFT', trade_type='BUY',
        quantity=2, price=Decimal('300.00'),
        notes='Cloud growth looks solid this quarter.',
    )
    response = auth_client.get('/trades/')
    assert b'Cloud growth looks solid this quarter.' in response.content


@pytest.mark.django_db
def test_notes_over_500_chars_rejected(auth_client):
    """Submitting notes longer than 500 characters should return a form error."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '1',
            'notes': 'x' * 501,
        })

    assert response.status_code == 200
    assert b'500 characters' in response.content
    assert Trade.objects.count() == 0


# ── UserProfile / Cash Balance ────────────────────────────────────────────────

@pytest.mark.django_db
def test_registration_creates_user_profile(client):
    """Registering a new user should auto-create a UserProfile with $100,000 starting cash."""
    client.post('/accounts/register/', {
        'username': 'newtrader99',
        'password1': 'StrongPass123!',
        'password2': 'StrongPass123!',
    })
    new_user = get_user_model().objects.get(username='newtrader99')
    assert hasattr(new_user, 'profile')
    assert new_user.profile.cash_balance == Decimal('100000.00')
    assert new_user.profile.starting_balance == Decimal('100000.00')


@pytest.mark.django_db
def test_buy_decrements_cash_balance(auth_client, user):
    """Completing a buy through the full view flow should reduce profile.cash_balance."""
    initial_cash = user.profile.cash_balance
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '5'})
        auth_client.post('/trade/new/', {'form_action': 'confirm'})
    user.profile.refresh_from_db()
    assert user.profile.cash_balance == initial_cash - Decimal('500.00')


@pytest.mark.django_db
def test_sell_increments_cash_balance(auth_client, user):
    """Completing a sell through the full view flow should increase profile.cash_balance."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=10, price=Decimal('100.00'))
    user.profile.cash_balance = Decimal('99000.00')
    user.profile.save()
    initial_cash = user.profile.cash_balance
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [120.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'SELL', 'quantity': '5'})
        auth_client.post('/trade/new/', {'form_action': 'confirm'})
    user.profile.refresh_from_db()
    assert user.profile.cash_balance == initial_cash + Decimal('600.00')


@pytest.mark.django_db
def test_buy_blocked_insufficient_cash_at_review(auth_client, user):
    """A buy should be blocked at the review step if the user's profile cash is too low."""
    user.profile.cash_balance = Decimal('500.00')
    user.profile.save()
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '10',
        })
    assert response.status_code == 200
    assert 'Insufficient funds' in response.content.decode()
    assert Trade.objects.filter(user=user).count() == 0


@pytest.mark.django_db
def test_buy_blocked_insufficient_cash_at_confirm(auth_client, user):
    """A buy should be blocked at the confirm step if cash was depleted after the review step."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '5'})
    user.profile.cash_balance = Decimal('0.00')
    user.profile.save()
    response = auth_client.post('/trade/new/', {'form_action': 'confirm'})
    assert response.status_code == 200
    assert 'Insufficient funds' in response.content.decode()
    assert Trade.objects.count() == 0


@pytest.mark.django_db
def test_portfolio_displays_cash_balance(auth_client, user):
    """The portfolio page should show the cash balance from the user's profile."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '1'})
        auth_client.post('/trade/new/', {'form_action': 'confirm'})
    user.profile.refresh_from_db()
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        response = auth_client.get('/portfolio/')
    assert response.status_code == 200
    # $100,000 - $100 = $99,900 shown as 99900.00 by floatformat:2
    assert '99900.00' in response.content.decode()


@pytest.mark.django_db
def test_oversell_still_blocked_after_profile_changes(auth_client, user):
    """Share ownership validation should still block oversells regardless of cash balance changes."""
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=2, price=Decimal('100.00'))
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        response = auth_client.post('/trade/new/', {
            'ticker': 'AAPL', 'trade_type': 'SELL', 'quantity': '5',
        })
    assert response.status_code == 200
    assert 'You cannot sell more shares than you currently own.' in response.content.decode()
    assert Trade.objects.filter(trade_type='SELL').count() == 0


@pytest.mark.django_db
def test_clear_trades_resets_cash_balance(auth_client, user):
    """Clearing trades should reset profile.cash_balance back to starting_balance."""
    with patch('trading.views.yf.Ticker') as mock_ticker:
        mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [100.00]})
        auth_client.post('/trade/new/', {'ticker': 'AAPL', 'trade_type': 'BUY', 'quantity': '5'})
        auth_client.post('/trade/new/', {'form_action': 'confirm'})
    user.profile.refresh_from_db()
    assert user.profile.cash_balance < user.profile.starting_balance

    auth_client.post('/demo/clear/')
    user.profile.refresh_from_db()
    assert user.profile.cash_balance == user.profile.starting_balance


@pytest.mark.django_db
def test_watchlist_rejects_ticker_too_long(auth_client, user):
    """A ticker longer than 10 characters should show a clear error message."""
    response = auth_client.post('/watchlist/', {'ticker': 'TOOLONGTICKER'})
    assert response.status_code == 200
    assert '10 characters' in response.content.decode()
    assert WatchlistItem.objects.filter(user=user).count() == 0


# ── AI Coach Tests ────────────────────────────────────────────────────────────

@pytest.mark.django_db
@patch('trading.services.ai_coach.yf.Ticker')
def test_build_portfolio_context_correct_structure(mock_ticker, user):
    """build_portfolio_context returns all expected keys and correct holding count."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
    Trade.objects.create(user=user, ticker='AAPL', trade_type='BUY', quantity=5, price=Decimal('100.00'))

    ctx = build_portfolio_context(user)

    expected_keys = {'cash_balance', 'starting_balance', 'total_portfolio_value', 'total_return_pct',
                     'holdings', 'recent_trades', 'trade_count_total', 'trade_count_30d', 'concentration'}
    assert expected_keys <= ctx.keys()
    assert ctx['trade_count_total'] == 1
    assert len(ctx['holdings']) == 1
    assert ctx['holdings'][0]['ticker'] == 'AAPL'


@pytest.mark.django_db
def test_build_portfolio_context_empty_user(user):
    """build_portfolio_context handles a user with no trades gracefully."""
    ctx = build_portfolio_context(user)

    assert ctx['trade_count_total'] == 0
    assert ctx['holdings'] == []
    assert ctx['recent_trades'] == []
    assert ctx['concentration'] == 0.0


@pytest.mark.django_db
@patch('trading.services.ai_coach.yf.Ticker')
@patch('trading.services.ai_coach.anthropic.Anthropic')
def test_get_coach_analysis_saves_row_on_success(mock_anthropic_class, mock_ticker, user):
    """get_coach_analysis saves a CoachAnalysis row when the API call succeeds."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
    mock_message = MagicMock()
    mock_message.content = [MagicMock(text="Good diversification. Watch your cash. What is your goal?")]
    mock_anthropic_class.return_value.messages.create.return_value = mock_message

    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key-123'}):
        result = get_coach_analysis(user)

    assert CoachAnalysis.objects.filter(user=user).count() == 1
    saved = CoachAnalysis.objects.get(user=user)
    assert 'Good diversification' in saved.analysis_text
    assert 'Good diversification' in result


@pytest.mark.django_db
@patch('trading.services.ai_coach.yf.Ticker')
@patch('trading.services.ai_coach.anthropic.Anthropic')
def test_get_coach_analysis_api_failure_no_row_saved(mock_anthropic_class, mock_ticker, user):
    """get_coach_analysis returns a fallback string and saves nothing when the API raises."""
    mock_ticker.return_value.history.return_value = pd.DataFrame({'Close': [150.00]})
    mock_anthropic_class.return_value.messages.create.side_effect = Exception("Network error")

    with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'test-key-123'}):
        result = get_coach_analysis(user)

    assert CoachAnalysis.objects.filter(user=user).count() == 0
    assert isinstance(result, str)
    assert len(result) > 0


@pytest.mark.django_db
def test_coach_view_get_renders(auth_client):
    """The portfolio page includes the AI Trading Coach section."""
    response = auth_client.get('/portfolio/')
    assert response.status_code == 200
    assert 'AI Trading Coach' in response.content.decode()


@pytest.mark.django_db
@patch('trading.views.get_coach_analysis')
def test_coach_view_post_triggers_analysis(mock_get_analysis, auth_client):
    """POSTing action=coach to the portfolio page calls get_coach_analysis."""
    mock_get_analysis.return_value = "Test analysis."

    response = auth_client.post('/portfolio/', {'action': 'coach'})

    assert response.status_code == 200
    mock_get_analysis.assert_called_once()


@pytest.mark.django_db
@patch('trading.views.get_coach_analysis')
def test_coach_view_rate_limit_blocks_second_post(mock_get_analysis, auth_client, user):
    """A second coach POST within 60 seconds is blocked with a wait message."""
    mock_get_analysis.return_value = "Analysis."
    CoachAnalysis.objects.create(user=user, portfolio_snapshot={}, analysis_text="Previous analysis.")

    response = auth_client.post('/portfolio/', {'action': 'coach'}, follow=True)

    mock_get_analysis.assert_not_called()
    assert 'Please wait' in response.content.decode()


@pytest.mark.django_db
@patch('trading.services.ai_coach.config', return_value=None)
def test_missing_api_key_returns_friendly_message(mock_config, user):
    """get_coach_analysis returns a friendly string and saves nothing when the API key is absent."""
    result = get_coach_analysis(user)

    assert isinstance(result, str)
    assert len(result) > 0
    assert CoachAnalysis.objects.filter(user=user).count() == 0


# ── format_large_number unit tests ────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (None,                  '—'),
    ('not a number',        '—'),
    (0,                     '0'),
    (999,                   '999'),
    (1_500,                 '1.5K'),
    (2_500_000_000,         '2.5B'),
    (3_000_000_000_000,     '3.0T'),
    (-2_500_000_000,        '-2.5B'),
])
def test_format_large_number(value, expected):
    assert format_large_number(value) == expected


# ── market_data caching unit tests ────────────────────────────────────────────

@patch('trading.services.market_data.yf.Ticker')
def test_get_stock_history_caches_valid_result(mock_ticker):
    """A second call with the same args should use the cache — yfinance called only once."""
    mock_df = pd.DataFrame(
        {'Close': [100.0], 'High': [101.0], 'Low': [99.0], 'Open': [100.0], 'Volume': [1_000_000]},
        index=pd.date_range('2024-01-02', periods=1),
    )
    mock_ticker.return_value.history.return_value = mock_df

    get_stock_history('CACHETEST1', '1mo')
    get_stock_history('CACHETEST1', '1mo')  # second call — should hit cache

    assert mock_ticker.return_value.history.call_count == 1


@patch('trading.services.market_data.yf.Ticker')
def test_get_stock_history_caches_empty_result_for_invalid_ticker(mock_ticker):
    """An invalid ticker (empty DataFrame) is cached to avoid hammering yfinance."""
    mock_ticker.return_value.history.return_value = pd.DataFrame()

    get_stock_history('ZZZBADTICKER', '2d')
    get_stock_history('ZZZBADTICKER', '2d')  # second call — should use cache

    assert mock_ticker.return_value.history.call_count == 1


@patch('trading.services.market_data.yf.Ticker')
def test_get_stock_info_returns_empty_dict_on_exception(mock_ticker):
    """When yf.Ticker().info raises, get_stock_info returns {} without propagating the error."""
    from unittest.mock import PropertyMock
    type(mock_ticker.return_value).info = PropertyMock(side_effect=Exception('network error'))

    result = get_stock_info('ERRTEST')

    assert result == {}


# ── stock_detail view tests ───────────────────────────────────────────────────

def _make_hist_df(rows=5):
    """Return a minimal yfinance-style history DataFrame with required columns."""
    dates = pd.date_range('2024-01-02', periods=rows)
    return pd.DataFrame(
        {
            'Close': [150.0 + i for i in range(rows)],
            'High':  [152.0 + i for i in range(rows)],
            'Low':   [148.0 + i for i in range(rows)],
            'Open':  [149.0 + i for i in range(rows)],
            'Volume': [1_000_000] * rows,
        },
        index=dates,
    )


@pytest.mark.django_db
@patch('trading.services.market_data.yf.Ticker')
def test_stock_detail_invalid_ticker_shows_error_not_crash(mock_ticker, auth_client):
    """An invalid ticker (empty history) shows an error message and returns 200."""
    mock_ticker.return_value.history.return_value = pd.DataFrame()

    response = auth_client.get('/stock/ZZZZ/')

    assert response.status_code == 200
    assert 'No stock data found for that ticker.' in response.content.decode()


@pytest.mark.django_db
@patch('trading.services.market_data.yf.Ticker')
def test_stock_detail_empty_info_shows_stats_error(mock_ticker, auth_client):
    """When .info returns {}, stats_error is displayed and the page does not crash."""
    def history_side_effect(period=None, interval='1d', **kwargs):
        return _make_hist_df(rows=2)

    mock_ticker.return_value.history.side_effect = history_side_effect
    mock_ticker.return_value.info = {}
    mock_ticker.return_value.news = []

    response = auth_client.get('/stock/INFOERR/')

    assert response.status_code == 200
    assert 'Additional data unavailable right now.' in response.content.decode()


@pytest.mark.django_db
@patch('trading.services.market_data.yf.Ticker')
def test_stock_detail_sparse_info_shows_dashes_not_none(mock_ticker, auth_client):
    """Missing .info fields render as '—' in the stats grid — never as Python 'None'."""
    def history_side_effect(period=None, interval='1d', **kwargs):
        return _make_hist_df(rows=50 if period == '5y' else 2)

    mock_ticker.return_value.history.side_effect = history_side_effect
    mock_ticker.return_value.info = {'shortName': 'Test Corp'}  # most fields absent
    mock_ticker.return_value.news = []

    response = auth_client.get('/stock/SPARSE/')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Key Statistics' in body
    assert 'None' not in body  # raw Python None must never leak into the HTML


@pytest.mark.django_db
@patch('trading.services.market_data.yf.Ticker')
def test_stock_detail_valid_ticker_renders_all_sections(mock_ticker, auth_client):
    """A fully-mocked valid ticker renders company name, stats, description, and news."""
    def history_side_effect(period=None, interval='1d', **kwargs):
        return _make_hist_df(rows=50 if period == '5y' else 2)

    mock_ticker.return_value.history.side_effect = history_side_effect
    mock_ticker.return_value.info = {
        'shortName': 'Apple Inc.',
        'marketCap': 2_980_000_000_000,
        'trailingPE': 28.5,
        'sector': 'Technology',
        'industry': 'Consumer Electronics',
        'longBusinessSummary': 'Apple Inc. designs, manufactures, and markets consumer electronics.',
    }
    mock_ticker.return_value.news = [
        {
            'title': 'Apple hits new high',
            'publisher': 'Reuters',
            'link': 'https://example.com/news1',
            'providerPublishTime': 1_700_000_000,
        },
    ]

    response = auth_client.get('/stock/AAPL/')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Apple Inc.' in body             # company name in header
    assert 'Key Statistics' in body         # stats grid rendered
    assert 'Technology' in body             # sector field
    assert 'Apple Inc. designs' in body     # company description


@pytest.mark.django_db
@patch('trading.services.market_data.yf.Ticker')
def test_stock_detail_graceful_degradation_when_5y_history_fails(mock_ticker, auth_client):
    """When 5Y history returns empty, chart_error is shown but key stats still render."""
    def history_side_effect(period=None, interval='1d', **kwargs):
        if period == '2d':
            return _make_hist_df(rows=2)
        return pd.DataFrame()  # empty for 5y and intraday

    mock_ticker.return_value.history.side_effect = history_side_effect
    mock_ticker.return_value.info = {
        'shortName': 'Apple Inc.',
        'sector': 'Technology',
    }
    mock_ticker.return_value.news = []

    response = auth_client.get('/stock/AAPL/')

    assert response.status_code == 200
    body = response.content.decode()
    assert 'Price chart unavailable right now.' in body  # chart_error shown
    assert 'Key Statistics' in body                      # stats still rendered
