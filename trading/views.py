from decimal import Decimal

from django.shortcuts import redirect, render
import yfinance as yf

from .models import Trade
# Create your views here.



def index(request):
    """Home page for the paper trading app."""
    return render(request, 'trading/index.html')

def search(request):
    """Handle ticker search and fetch stock data."""
    ticker = None
    price = None
    error_message = None

    if 'ticker' in request.GET:
        # Clean up the user's input so we search with a simple ticker value.
        ticker = request.GET['ticker'].strip().upper()

        if ticker:
            try:
                stock = yf.Ticker(ticker)
                data = stock.history(period='1d')

                if not data.empty:
                    price = round(float(data['Close'].iloc[-1]), 2)
                else:
                    error_message = 'No stock data was found for that ticker.'
            except Exception:
                error_message = 'Could not fetch stock data right now.'
        else:
            error_message = 'Please enter a ticker symbol.'

    return render(request, 'trading/search.html', {
        'ticker': ticker,
        'price': price,
        'error_message': error_message,
    })


def create_trade(request):
    """Show a simple form and save a paper trade."""
    # Start the paper trading account with a simple fixed cash amount.
    starting_cash = Decimal('10000.00')
    ticker = ''
    trade_type = 'BUY'
    quantity = ''
    success_message = None
    error_message = None

    if request.method == 'POST':
        # Read the values the user typed into the form.
        ticker = request.POST.get('ticker', '').strip().upper()
        trade_type = request.POST.get('trade_type', 'BUY')
        quantity = request.POST.get('quantity', '').strip()

        # Make sure the form is filled in before we try to save.
        if ticker and trade_type and quantity:
            try:
                quantity_value = int(quantity)

                if quantity_value > 0:
                    # Fetch the current market price automatically for the trade.
                    price_value = None

                    try:
                        stock = yf.Ticker(ticker)
                        data = stock.history(period='1d')

                        if not data.empty:
                            latest_price = round(float(data['Close'].iloc[-1]), 2)
                            price_value = Decimal(str(latest_price))
                        else:
                            error_message = 'Could not fetch a current price for that ticker.'
                    except Exception:
                        error_message = 'Could not fetch a current price right now.'

                    if price_value is not None:
                        # Work out the current cash balance before saving a new trade.
                        cash_balance = starting_cash
                        all_trades = Trade.objects.all()

                        for trade in all_trades:
                            trade_total = trade.quantity * trade.price

                            if trade.trade_type == 'BUY':
                                cash_balance -= trade_total
                            elif trade.trade_type == 'SELL':
                                cash_balance += trade_total

                        # Count current shares for this ticker before saving a sell.
                        current_shares = 0
                        existing_trades = Trade.objects.filter(ticker=ticker)

                        for trade in existing_trades:
                            if trade.trade_type == 'BUY':
                                current_shares += trade.quantity
                            elif trade.trade_type == 'SELL':
                                current_shares -= trade.quantity

                        # Block sells that are larger than the shares owned.
                        if trade_type == 'SELL' and quantity_value > current_shares:
                            error_message = 'You cannot sell more shares than you currently own.'
                        # Block buys that cost more cash than is available.
                        elif trade_type == 'BUY' and (quantity_value * price_value) > cash_balance:
                            error_message = 'You do not have enough cash to make that purchase.'
                        else:
                            # Save one row in the Trade table using the fetched price.
                            Trade.objects.create(
                                ticker=ticker,
                                trade_type=trade_type,
                                quantity=quantity_value,
                                price=price_value,
                            )
                            success_message = f'Trade saved successfully at ${price_value} per share.'

                            # Clear the form after a successful save.
                            ticker = ''
                            trade_type = 'BUY'
                            quantity = ''
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
    })


def trade_history(request):
    """Show all saved trades, newest first."""
    # Load trades from the database so the template can display them.
    trades = Trade.objects.order_by('-created_at')

    return render(request, 'trading/trade_history.html', {
        'trades': trades,
    })


def portfolio(request):
    """Show current holdings based on saved trades."""
    # Show a simple message after clearing trades.
    trades_cleared = request.GET.get('demo') == 'cleared'
    # Start with all saved trades in the database.
    trades = Trade.objects.order_by('ticker', 'created_at')
    holdings = {}
    # Give the paper trading account a simple starting cash amount.
    starting_cash = Decimal('10000.00')
    cash_balance = starting_cash
    total_holdings_value = Decimal('0.00')

    # Go through each trade and update the running share total.
    for trade in trades:
        if trade.ticker not in holdings:
            holdings[trade.ticker] = 0

        # Calculate how much money this trade changes in the account.
        trade_total = trade.quantity * trade.price

        if trade.trade_type == 'BUY':
            holdings[trade.ticker] += trade.quantity
            cash_balance -= trade_total
        elif trade.trade_type == 'SELL':
            holdings[trade.ticker] -= trade.quantity
            cash_balance += trade_total

    # Convert the dictionary into a list the template can loop through.
    portfolio_rows = []
    for ticker, shares in holdings.items():
        # Only show tickers where the user still owns shares.
        if shares > 0:
            current_price = None
            total_value = None

            try:
                # Load the latest closing price for this ticker.
                stock = yf.Ticker(ticker)
                data = stock.history(period='1d')

                if not data.empty:
                    latest_price = round(float(data['Close'].iloc[-1]), 2)
                    current_price = Decimal(str(latest_price))
                    total_value = shares * current_price
                    total_holdings_value += total_value
            except Exception:
                # Keep the page working even if price data is unavailable.
                current_price = None
                total_value = None

            portfolio_rows.append({
                'ticker': ticker,
                'shares': shares,
                'current_price': current_price,
                'total_value': total_value,
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


def clear_trades(request):
    """Delete all trades so the app returns to an empty state."""
    if request.method == 'POST':
        # Remove all saved trades from the database.
        Trade.objects.all().delete()
        return redirect('/portfolio/?demo=cleared')

    return redirect('trading:index')
