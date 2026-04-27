import pandas as pd
from django.core.cache import cache
import yfinance as yf


def get_stock_history(ticker, period='1mo', interval='1d'):
    """
    Return yfinance history DataFrame for the given ticker.
    Valid data is cached for 5 minutes; empty/invalid results for 60 seconds.
    Never raises — returns an empty DataFrame on any error.
    """
    cache_key = f"stock_hist_{ticker}_{period}_{interval}"
    wrapped = cache.get(cache_key)
    if wrapped is not None:
        return wrapped['data']

    try:
        data = yf.Ticker(ticker).history(period=period, interval=interval)
    except Exception:
        data = pd.DataFrame()

    ttl = 60 if data.empty else 300
    cache.set(cache_key, {'data': data}, ttl)
    return data


def get_stock_info(ticker):
    """
    Return yfinance .info dict for the given ticker.
    Valid results cached for 5 minutes; failures return {} and cache for 60 seconds.
    Never raises.
    """
    cache_key = f"stock_info_{ticker}"
    wrapped = cache.get(cache_key)
    if wrapped is not None:
        return wrapped['data']

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        info = {}

    ttl = 60 if not info else 300
    cache.set(cache_key, {'data': info}, ttl)
    return info


def get_stock_news(ticker):
    """Return up to 5 recent news items for a ticker, or empty list on error."""
    try:
        news = yf.Ticker(ticker).news
        return (news or [])[:5]
    except Exception:
        return []
