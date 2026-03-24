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

    if 'ticker' in request.GET:
        ticker = request.GET['ticker']

        stock = yf.Ticker(ticker)
        data = stock.history(period='1d')

        if not data.empty:
            price = data['Close'].iloc[-1]

    return render(request, 'trading/search.html', {
        'ticker': ticker,
        'price': price
    })