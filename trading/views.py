from decimal import Decimal, InvalidOperation

from django.shortcuts import render
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
            stock = yf.Ticker(ticker)
            data = stock.history(period='1d')

            if not data.empty:
                price = data['Close'].iloc[-1]
            else:
                error_message = 'No stock data was found for that ticker.'
        else:
            error_message = 'Please enter a ticker symbol.'

    return render(request, 'trading/search.html', {
        'ticker': ticker,
        'price': price,
        'error_message': error_message,
    })


def create_trade(request):
    """Show a simple form and save a paper trade."""
    ticker = ''
    trade_type = 'BUY'
    quantity = ''
    price = ''
    success_message = None
    error_message = None

    if request.method == 'POST':
        # Read the values the user typed into the form.
        ticker = request.POST.get('ticker', '').strip().upper()
        trade_type = request.POST.get('trade_type', 'BUY')
        quantity = request.POST.get('quantity', '').strip()
        price = request.POST.get('price', '').strip()

        # Make sure the form is filled in before we try to save.
        if ticker and trade_type and quantity and price:
            try:
                quantity_value = int(quantity)
                price_value = Decimal(price)

                if quantity_value > 0 and price_value > 0:
                    # Save one row in the Trade table.
                    Trade.objects.create(
                        ticker=ticker,
                        trade_type=trade_type,
                        quantity=quantity_value,
                        price=price_value,
                    )
                    success_message = 'Trade saved successfully.'

                    # Clear the form after a successful save.
                    ticker = ''
                    trade_type = 'BUY'
                    quantity = ''
                    price = ''
                else:
                    error_message = 'Quantity and price must be greater than zero.'
            except (ValueError, InvalidOperation):
                error_message = 'Enter a valid quantity and price.'
        else:
            error_message = 'Please fill in every field.'

    return render(request, 'trading/trade_form.html', {
        'ticker': ticker,
        'trade_type': trade_type,
        'quantity': quantity,
        'price': price,
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
    # Start with all saved trades in the database.
    trades = Trade.objects.order_by('ticker', 'created_at')
    holdings = {}

    # Go through each trade and update the running share total.
    for trade in trades:
        if trade.ticker not in holdings:
            holdings[trade.ticker] = 0

        if trade.trade_type == 'BUY':
            holdings[trade.ticker] += trade.quantity
        elif trade.trade_type == 'SELL':
            holdings[trade.ticker] -= trade.quantity

    # Convert the dictionary into a list the template can loop through.
    portfolio_rows = []
    for ticker, shares in holdings.items():
        # Only show tickers where the user still owns shares.
        if shares > 0:
            portfolio_rows.append({
                'ticker': ticker,
                'shares': shares,
            })

    return render(request, 'trading/portfolio.html', {
        'portfolio_rows': portfolio_rows,
    })
