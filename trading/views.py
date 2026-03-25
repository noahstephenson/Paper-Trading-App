from decimal import Decimal, InvalidOperation

from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
import yfinance as yf

from .models import Trade
# Create your views here.

VALID_TRADE_TYPES = {Trade.BUY, Trade.SELL}


def fetch_latest_price(ticker):
    """Return the latest available price for a ticker, or None."""
    stock = yf.Ticker(ticker)
    data = stock.history(period='1d')

    if data.empty:
        return None

    latest_price = round(float(data['Close'].iloc[-1]), 2)
    return Decimal(str(latest_price))


def get_trade_balances(user, ticker, starting_cash):
    """Calculate available cash and currently owned shares for one user."""
    cash_balance = starting_cash
    current_shares = 0
    all_trades = Trade.objects.filter(user=user)

    for trade in all_trades:
        trade_total = trade.quantity * trade.price

        if trade.trade_type == Trade.BUY:
            cash_balance -= trade_total
        elif trade.trade_type == Trade.SELL:
            cash_balance += trade_total

        if trade.ticker == ticker:
            if trade.trade_type == Trade.BUY:
                current_shares += trade.quantity
            elif trade.trade_type == Trade.SELL:
                current_shares -= trade.quantity

    return cash_balance, current_shares



def index(request):
    """Home page for the paper trading app."""
    starting_cash = Decimal('10000.00')
    if request.user.is_authenticated:
        trades = Trade.objects.filter(user=request.user)
    else:
        trades = Trade.objects.none()
    trade_count = trades.count()
    holdings = {}

    for trade in trades:
        if trade.ticker not in holdings:
            holdings[trade.ticker] = 0

        if trade.trade_type == 'BUY':
            holdings[trade.ticker] += trade.quantity
        elif trade.trade_type == 'SELL':
            holdings[trade.ticker] -= trade.quantity

    active_holdings_count = sum(1 for shares in holdings.values() if shares > 0)

    return render(request, 'trading/index.html', {
        'starting_cash': starting_cash,
        'trade_count': trade_count,
        'active_holdings_count': active_holdings_count,
    })


def register(request):
    """Allow a new user to create a simple account."""
    if request.user.is_authenticated:
        return redirect('trading:index')

    if request.method == 'POST':
        form = UserCreationForm(data=request.POST)

        if form.is_valid():
            form.save()
            return redirect('/accounts/login/?registered=1')
    else:
        form = UserCreationForm()

    return render(request, 'registration/register.html', {
        'form': form,
    })

@login_required
def search(request):
    """Handle ticker search and fetch stock data."""
    ticker = None
    price = None
    company_name = None
    stock_details = None
    error_message = None

    if 'ticker' in request.GET:
        # Clean up the user's input so we search with a simple ticker value.
        ticker = request.GET['ticker'].strip().upper()

        if ticker:
            try:
                stock = yf.Ticker(ticker)
                data = stock.history(period='2d')
                try:
                    company_name = stock.info.get('shortName')
                except Exception:
                    company_name = None

                if not data.empty:
                    latest_row = data.iloc[-1]
                    price = round(float(latest_row['Close']), 2)
                    stock_details = {
                        'day_high': round(float(latest_row['High']), 2),
                        'day_low': round(float(latest_row['Low']), 2),
                    }

                    if len(data) > 1:
                        previous_close = round(float(data['Close'].iloc[-2]), 2)
                        daily_change = round(price - previous_close, 2)
                        if previous_close != 0:
                            daily_change_percent = round((daily_change / previous_close) * 100, 2)
                        else:
                            daily_change_percent = 0

                        stock_details['previous_close'] = previous_close
                        stock_details['daily_change'] = daily_change
                        stock_details['daily_change_percent'] = daily_change_percent
                else:
                    error_message = 'No stock data was found for that ticker.'
            except Exception:
                error_message = 'Could not fetch stock data right now.'
        else:
            error_message = 'Please enter a ticker symbol.'

    return render(request, 'trading/search.html', {
        'ticker': ticker,
        'price': price,
        'company_name': company_name,
        'stock_details': stock_details,
        'error_message': error_message,
    })


@login_required
def create_trade(request):
    """Show a simple form and save a paper trade."""
    # Start the paper trading account with a simple fixed cash amount.
    starting_cash = Decimal('10000.00')
    ticker = request.GET.get('ticker', '').strip().upper() if request.method == 'GET' else ''
    trade_type = 'BUY'
    quantity = ''
    success_message = request.session.pop('trade_success_message', None)
    error_message = None
    confirm_trade = False
    quoted_price = None
    estimated_total = None

    # Only allow confirmation right after a review step, not from an old page load.
    if request.method != 'POST':
        request.session.pop('pending_trade', None)

    if request.method == 'POST':
        # A normal submit reviews the trade first. Only the confirm button saves it.
        form_action = request.POST.get('form_action', 'review')

        if form_action == 'confirm':
            pending_trade = request.session.get('pending_trade')

            if not pending_trade:
                error_message = 'Please submit the trade again before confirming it.'
            else:
                ticker = pending_trade.get('ticker', '')
                trade_type = pending_trade.get('trade_type', 'BUY')
                quantity = str(pending_trade.get('quantity', ''))

                try:
                    quantity_value = int(quantity)
                    price_value = Decimal(pending_trade.get('quoted_price', ''))
                except (ValueError, InvalidOperation, TypeError):
                    quantity_value = None
                    price_value = None

                if trade_type not in VALID_TRADE_TYPES or quantity_value is None or price_value is None:
                    request.session.pop('pending_trade', None)
                    error_message = 'Could not confirm that trade. Please submit it again.'
                else:
                    cash_balance, current_shares = get_trade_balances(
                        request.user,
                        ticker,
                        starting_cash,
                    )

                    # Block sells that are larger than the shares owned.
                    if trade_type == Trade.SELL and quantity_value > current_shares:
                        request.session.pop('pending_trade', None)
                        error_message = 'You cannot sell more shares than you currently own.'
                    # Block buys that cost more cash than is available.
                    elif trade_type == Trade.BUY and (quantity_value * price_value) > cash_balance:
                        request.session.pop('pending_trade', None)
                        error_message = 'You do not have enough cash to make that purchase.'
                    else:
                        # Save one row in the Trade table using the reviewed server-side price.
                        Trade.objects.create(
                            user=request.user,
                            ticker=ticker,
                            trade_type=trade_type,
                            quantity=quantity_value,
                            price=price_value,
                        )
                        trade_total = quantity_value * price_value
                        request.session.pop('pending_trade', None)
                        request.session['trade_success_message'] = (
                            f'{trade_type} trade confirmed for {quantity_value} shares of '
                            f'{ticker} at ${price_value:.2f} per share. '
                            f'Estimated total: ${trade_total:.2f}.'
                        )
                        return redirect('trading:create_trade')
        else:
            # Read the values the user typed into the form.
            ticker = request.POST.get('ticker', '').strip().upper()
            trade_type = request.POST.get('trade_type', 'BUY')
            quantity = request.POST.get('quantity', '').strip()

            # Make sure the form is filled in before we try to review the trade.
            if ticker and trade_type and quantity:
                if trade_type not in VALID_TRADE_TYPES:
                    error_message = 'Choose a valid trade type.'
                else:
                    try:
                        quantity_value = int(quantity)

                        if quantity_value > 0:
                            # Automatically fetch the current market price for review.
                            try:
                                price_value = fetch_latest_price(ticker)
                            except Exception:
                                price_value = None
                                error_message = 'Could not fetch a current price right now.'

                            if price_value is None and error_message is None:
                                error_message = 'Could not fetch a current price for that ticker.'
                            elif price_value is not None:
                                cash_balance, current_shares = get_trade_balances(
                                    request.user,
                                    ticker,
                                    starting_cash,
                                )

                                # Block sells that are larger than the shares owned.
                                if trade_type == Trade.SELL and quantity_value > current_shares:
                                    error_message = 'You cannot sell more shares than you currently own.'
                                # Block buys that cost more cash than is available.
                                elif trade_type == Trade.BUY and (quantity_value * price_value) > cash_balance:
                                    error_message = 'You do not have enough cash to make that purchase.'
                                else:
                                    quoted_price = price_value
                                    estimated_total = quantity_value * quoted_price
                                    confirm_trade = True
                                    request.session['pending_trade'] = {
                                        'ticker': ticker,
                                        'trade_type': trade_type,
                                        'quantity': quantity_value,
                                        'quoted_price': str(quoted_price),
                                    }
                        else:
                            error_message = 'Quantity must be greater than zero.'
                    except ValueError:
                        error_message = 'Enter a valid quantity.'
            else:
                error_message = 'Please fill in every field.'

    return render(request, 'trading/trade_form.html', {
        'ticker': ticker,
        'trade_type': trade_type,
        'quantity': quantity,
        'success_message': success_message,
        'error_message': error_message,
        'confirm_trade': confirm_trade,
        'quoted_price': quoted_price,
        'estimated_total': estimated_total,
    })


@login_required
def trade_history(request):
    """Show all saved trades, newest first."""
    # Load trades from the database so the template can display them.
    trades = Trade.objects.filter(user=request.user).order_by('-created_at')

    return render(request, 'trading/trade_history.html', {
        'trades': trades,
    })


@login_required
def portfolio(request):
    """Show current holdings based on saved trades."""
    # Show a simple message after clearing trades.
    trades_cleared = request.GET.get('demo') == 'cleared'
    # Start with all saved trades in the database.
    trades = Trade.objects.filter(user=request.user).order_by('ticker', 'created_at')
    holdings = {}
    # Give the paper trading account a simple starting cash amount.
    starting_cash = Decimal('10000.00')
    cash_balance = starting_cash
    total_holdings_value = Decimal('0.00')

    # Go through each trade and update the running share total and cost basis.
    for trade in trades:
        if trade.ticker not in holdings:
            holdings[trade.ticker] = {
                'shares': 0,
                'total_cost': Decimal('0.00'),
            }

        # Calculate how much money this trade changes in the account.
        trade_total = trade.quantity * trade.price

        if trade.trade_type == 'BUY':
            holdings[trade.ticker]['shares'] += trade.quantity
            holdings[trade.ticker]['total_cost'] += trade_total
            cash_balance -= trade_total
        elif trade.trade_type == 'SELL':
            current_shares = holdings[trade.ticker]['shares']
            current_total_cost = holdings[trade.ticker]['total_cost']

            # Reduce remaining cost basis using the current average cost.
            if current_shares > 0:
                average_cost = current_total_cost / Decimal(current_shares)
                holdings[trade.ticker]['total_cost'] -= average_cost * trade.quantity

            holdings[trade.ticker]['shares'] -= trade.quantity
            cash_balance += trade_total

    # Convert the dictionary into a list the template can loop through.
    portfolio_rows = []
    for ticker, holding_data in holdings.items():
        shares = holding_data['shares']
        # Only show tickers where the user still owns shares.
        if shares > 0:
            current_price = None
            total_value = None
            average_cost = holding_data['total_cost'] / Decimal(shares)
            gain_loss = None
            gain_loss_per_share = None
            gain_loss_percent = None

            try:
                # Load the latest closing price for this ticker.
                stock = yf.Ticker(ticker)
                data = stock.history(period='1d')

                if not data.empty:
                    latest_price = round(float(data['Close'].iloc[-1]), 2)
                    current_price = Decimal(str(latest_price))
                    total_value = shares * current_price
                    gain_loss = total_value - holding_data['total_cost']
                    gain_loss_per_share = current_price - average_cost
                    if holding_data['total_cost'] > 0:
                        gain_loss_percent = (
                            gain_loss / holding_data['total_cost']
                        ) * Decimal('100')
                    total_holdings_value += total_value
            except Exception:
                # Keep the page working even if price data is unavailable.
                current_price = None
                total_value = None
                gain_loss = None
                gain_loss_per_share = None
                gain_loss_percent = None

            portfolio_rows.append({
                'ticker': ticker,
                'shares': shares,
                'average_cost': average_cost,
                'current_price': current_price,
                'total_value': total_value,
                'gain_loss': gain_loss,
                'gain_loss_per_share': gain_loss_per_share,
                'gain_loss_percent': gain_loss_percent,
            })

    # Total account value is the cash plus the current holdings value.
    total_account_value = cash_balance + total_holdings_value

    return render(request, 'trading/portfolio.html', {
        'portfolio_rows': portfolio_rows,
        'starting_cash': starting_cash,
        'cash_balance': cash_balance,
        'total_holdings_value': total_holdings_value,
        'total_account_value': total_account_value,
        'trades_cleared': trades_cleared,
    })


@login_required
def clear_trades(request):
    """Delete all trades so the app returns to an empty state."""
    if request.method == 'POST':
        # Remove all saved trades from the database.
        Trade.objects.filter(user=request.user).delete()
        return redirect('/portfolio/?demo=cleared')

    return redirect('trading:index')
