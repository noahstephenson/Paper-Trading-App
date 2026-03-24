from django.shortcuts import render
import yfinance as yf
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
