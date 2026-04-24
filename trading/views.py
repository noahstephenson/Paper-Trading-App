from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .forms import RegistrationForm
import plotly.graph_objects as go
import yfinance as yf

from .models import Trade, UserProfile, WatchlistItem, CoachAnalysis
from .services.portfolio import compute_trade_state
from .services.ai_coach import get_coach_analysis

VALID_TRADE_TYPES = {Trade.BUY, Trade.SELL}
STARTING_CASH = Decimal('100000.00')


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




def build_portfolio_history(trades, starting_cash=STARTING_CASH):
    """
    Build a daily portfolio value series using trade history and yfinance price data.
    Returns (dates_list, values_list) for Plotly, or (None, None) if insufficient data.
    """
    import pandas as pd

    if not trades:
        return None, None

    sorted_trades = sorted(trades, key=lambda t: t.created_at)
    first_date = sorted_trades[0].created_at.date()
    all_tickers = list({t.ticker for t in sorted_trades})

    price_histories = {}
    for ticker in all_tickers:
        try:
            hist = yf.Ticker(ticker).history(start=str(first_date))
            if not hist.empty:
                if hist.index.tz is not None:
                    hist.index = hist.index.tz_convert(None)
                price_histories[ticker] = hist['Close']
        except Exception:
            pass

    if not price_histories:
        return None, None

    all_dates = pd.DatetimeIndex([])
    for series in price_histories.values():
        all_dates = all_dates.union(series.index)
    all_dates = all_dates.sort_values()

    for ticker in price_histories:
        price_histories[ticker] = price_histories[ticker].reindex(all_dates).ffill()

    cash = float(starting_cash)
    state = {}
    trade_idx = 0
    chart_dates = []
    chart_values = []

    for dt in all_dates:
        dt_date = dt.date()
        while trade_idx < len(sorted_trades) and sorted_trades[trade_idx].created_at.date() <= dt_date:
            trade = sorted_trades[trade_idx]
            ticker = trade.ticker
            qty = trade.quantity
            price = float(trade.price)
            if ticker not in state:
                state[ticker] = {'shares': 0, 'total_cost': 0.0}
            if trade.trade_type == Trade.BUY:
                state[ticker]['shares'] += qty
                state[ticker]['total_cost'] += qty * price
                cash -= qty * price
            else:
                s = state[ticker]
                avg = s['total_cost'] / s['shares'] if s['shares'] > 0 else price
                s['total_cost'] -= avg * qty
                s['shares'] -= qty
                cash += qty * price
            trade_idx += 1

        total = cash
        for ticker, s in state.items():
            if s['shares'] > 0 and ticker in price_histories:
                p = price_histories[ticker].get(dt)
                if p is not None and not pd.isna(p):
                    total += s['shares'] * float(p)

        chart_dates.append(dt)
        chart_values.append(round(total, 2))

    return chart_dates, chart_values


def index(request):
    """Home page — shows a summary dashboard for logged-in users."""
    if not request.user.is_authenticated:
        return render(request, 'trading/index.html', {})

    trades = Trade.objects.filter(user=request.user).order_by('created_at')
    holdings, _, _, realized_gain = compute_trade_state(trades)
    cash_balance = request.user.profile.cash_balance

    total_holdings_value = Decimal('0.00')
    unrealized_gain = Decimal('0.00')
    daily_change = Decimal('0.00')
    holding_rows = []

    for ticker, h in holdings.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='2d')
            if not hist.empty:
                current_price = Decimal(str(round(float(hist['Close'].iloc[-1]), 2)))
                shares = h['shares']
                total_value = shares * current_price
                cost_basis = h['avg_cost'] * shares
                total_holdings_value += total_value
                unrealized_gain += total_value - cost_basis
                if len(hist) >= 2:
                    prev_price = Decimal(str(round(float(hist['Close'].iloc[-2]), 2)))
                    daily_change += (current_price - prev_price) * shares
                holding_rows.append({
                    'ticker': ticker,
                    'shares': shares,
                    'total_value': total_value,
                    'gain_loss': total_value - cost_basis,
                })
        except Exception:
            pass

    total_portfolio_value = cash_balance + total_holdings_value
    top_holdings = sorted(holding_rows, key=lambda r: r['total_value'], reverse=True)[:5]
    recent_trades = Trade.objects.filter(user=request.user).order_by('-created_at')[:5]

    return render(request, 'trading/index.html', {
        'starting_cash': STARTING_CASH,
        'total_portfolio_value': total_portfolio_value,
        'cash_balance': cash_balance,
        'unrealized_gain': unrealized_gain,
        'realized_gain': realized_gain,
        'daily_change': daily_change,
        'top_holdings': top_holdings,
        'recent_trades': recent_trades,
    })


def register(request):
    """Allow a new user to create a simple account."""
    if request.user.is_authenticated:
        return redirect('trading:index')

    if request.method == 'POST':
        form = RegistrationForm(data=request.POST)

        if form.is_valid():
            form.save()
            return redirect('/accounts/login/?registered=1')
    else:
        form = RegistrationForm()

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
    chart_html = None
    error_message = None

    if 'ticker' in request.GET:
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
                    try:
                        hist = stock.history(period='1mo')
                        if not hist.empty:
                            fig = go.Figure()
                            fig.add_trace(go.Scatter(
                                x=hist.index,
                                y=hist['Close'],
                                mode='lines',
                                name='Close',
                            ))
                            fig.update_layout(
                                title=f'{ticker} — Last 30 Days',
                                xaxis_title='Date',
                                yaxis_title='Price (USD)',
                                margin=dict(l=40, r=20, t=50, b=40),
                            )
                            chart_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
                    except Exception:
                        chart_html = None
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
        'chart_html': chart_html,
        'error_message': error_message,
    })


@login_required
def stock_detail(request, ticker):
    """Dedicated page for a single stock — price info, chart, watchlist, and trade links."""
    ticker = ticker.upper()

    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'add_watchlist':
            WatchlistItem.objects.get_or_create(user=request.user, ticker=ticker)
        elif action == 'remove_watchlist':
            WatchlistItem.objects.filter(user=request.user, ticker=ticker).delete()
        return redirect('trading:stock_detail', ticker=ticker)

    price = None
    company_name = None
    stock_details = None
    chart_html = None
    error_message = None
    on_watchlist = WatchlistItem.objects.filter(user=request.user, ticker=ticker).exists()

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
                daily_change_percent = round((daily_change / previous_close) * 100, 2) if previous_close != 0 else 0
                stock_details['previous_close'] = previous_close
                stock_details['daily_change'] = daily_change
                stock_details['daily_change_percent'] = daily_change_percent
            try:
                hist = stock.history(period='1mo')
                if not hist.empty:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=hist.index,
                        y=hist['Close'],
                        mode='lines',
                        name='Close',
                    ))
                    fig.update_layout(
                        title=f'{ticker} — Last 30 Days',
                        xaxis_title='Date',
                        yaxis_title='Price (USD)',
                        margin=dict(l=40, r=20, t=50, b=40),
                    )
                    chart_html = fig.to_html(full_html=False, include_plotlyjs='cdn')
            except Exception:
                chart_html = None
        else:
            error_message = 'No stock data found for that ticker.'
    except Exception:
        error_message = 'Could not fetch stock data right now.'

    trades = Trade.objects.filter(user=request.user).order_by('created_at')
    holdings, _, _, _ = compute_trade_state(trades)
    cash_balance = request.user.profile.cash_balance
    shares_owned = holdings.get(ticker, {}).get('shares', 0)

    return render(request, 'trading/stock_detail.html', {
        'ticker': ticker,
        'company_name': company_name,
        'price': price,
        'stock_details': stock_details,
        'chart_html': chart_html,
        'error_message': error_message,
        'on_watchlist': on_watchlist,
        'shares_owned': shares_owned,
        'cash_balance': cash_balance,
    })


@login_required
def create_trade(request):
    """Show a simple form and save a paper trade."""
    ticker = request.GET.get('ticker', '').strip().upper() if request.method == 'GET' else ''
    ticker_prefilled = bool(ticker)
    trade_type = 'BUY'
    quantity = ''
    notes = ''
    cash_balance = request.user.profile.cash_balance
    success_message = request.session.pop('trade_success_message', None)
    error_message = None
    notes_error = None
    confirm_trade = False
    quoted_price = None
    estimated_total = None

    if request.method != 'POST':
        request.session.pop('pending_trade', None)

    if request.method == 'POST':
        form_action = request.POST.get('form_action', 'review')

        if form_action == 'confirm':
            pending_trade = request.session.get('pending_trade')

            if not pending_trade:
                error_message = 'Please submit the trade again before confirming it.'
            else:
                ticker = pending_trade.get('ticker', '')
                trade_type = pending_trade.get('trade_type', 'BUY')
                quantity = str(pending_trade.get('quantity', ''))
                notes = pending_trade.get('notes', '')

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
                    _, current_shares = get_trade_balances(
                        request.user,
                        ticker,
                        STARTING_CASH,
                    )

                    if trade_type == Trade.SELL and quantity_value > current_shares:
                        request.session.pop('pending_trade', None)
                        error_message = 'You cannot sell more shares than you currently own.'
                    else:
                        with transaction.atomic():
                            profile = UserProfile.objects.select_for_update().get(user=request.user)
                            amount = quantity_value * price_value
                            if trade_type == Trade.BUY and amount > profile.cash_balance:
                                request.session.pop('pending_trade', None)
                                error_message = (
                                    f'Insufficient funds: this trade costs ${amount:,.2f} '
                                    f'but you have ${profile.cash_balance:,.2f} available.'
                                )
                            else:
                                if trade_type == Trade.BUY:
                                    profile.cash_balance -= amount
                                else:
                                    profile.cash_balance += amount
                                profile.save()
                                Trade.objects.create(
                                    user=request.user,
                                    ticker=ticker,
                                    trade_type=trade_type,
                                    quantity=quantity_value,
                                    price=price_value,
                                    notes=notes,
                                )
                                trade_total = amount
                                request.session.pop('pending_trade', None)
                                request.session['trade_success_message'] = (
                                    f'{trade_type} trade confirmed for {quantity_value} shares of '
                                    f'{ticker} at ${price_value:.2f} per share. '
                                    f'Estimated total: ${trade_total:.2f}.'
                                )
                                return redirect('trading:create_trade')
        else:
            ticker = request.POST.get('ticker', '').strip().upper()
            trade_type = request.POST.get('trade_type', 'BUY')
            quantity = request.POST.get('quantity', '').strip()
            notes = request.POST.get('notes', '').strip()

            if len(notes) > 500:
                notes_error = 'Notes must be 500 characters or fewer.'

            if ticker and trade_type and quantity and not notes_error:
                if trade_type not in VALID_TRADE_TYPES:
                    error_message = 'Choose a valid trade type.'
                else:
                    try:
                        quantity_value = int(quantity)

                        if quantity_value > 0:
                            try:
                                price_value = fetch_latest_price(ticker)
                            except Exception:
                                price_value = None
                                error_message = 'Could not fetch a current price right now.'

                            if price_value is None and error_message is None:
                                error_message = 'Could not fetch a current price for that ticker.'
                            elif price_value is not None:
                                _, current_shares = get_trade_balances(
                                    request.user,
                                    ticker,
                                    STARTING_CASH,
                                )
                                cash_balance = request.user.profile.cash_balance
                                trade_cost = quantity_value * price_value

                                if trade_type == Trade.SELL and quantity_value > current_shares:
                                    error_message = 'You cannot sell more shares than you currently own.'
                                elif trade_type == Trade.BUY and trade_cost > cash_balance:
                                    error_message = (
                                        f'Insufficient funds: this trade costs ${trade_cost:,.2f} '
                                        f'but you have ${cash_balance:,.2f} available.'
                                    )
                                else:
                                    quoted_price = price_value
                                    estimated_total = quantity_value * quoted_price
                                    confirm_trade = True
                                    request.session['pending_trade'] = {
                                        'ticker': ticker,
                                        'trade_type': trade_type,
                                        'quantity': quantity_value,
                                        'quoted_price': str(quoted_price),
                                        'notes': notes,
                                    }
                        else:
                            error_message = 'Quantity must be greater than zero.'
                    except ValueError:
                        error_message = 'Enter a valid quantity.'
            else:
                error_message = 'Please fill in every field.'

    return render(request, 'trading/trade_form.html', {
        'ticker': ticker,
        'ticker_prefilled': ticker_prefilled,
        'trade_type': trade_type,
        'quantity': quantity,
        'notes': notes,
        'cash_balance': cash_balance,
        'notes_error': notes_error,
        'success_message': success_message,
        'error_message': error_message,
        'confirm_trade': confirm_trade,
        'quoted_price': quoted_price,
        'estimated_total': estimated_total,
    })


@login_required
def trade_history(request):
    """Show all saved trades with running cash balance and realized gain on sells."""
    trades = Trade.objects.filter(user=request.user).order_by('created_at')
    _, annotated_trades, _, total_realized_gain = compute_trade_state(
        trades, starting_cash=request.user.profile.starting_balance
    )
    annotated_trades = list(reversed(annotated_trades))

    return render(request, 'trading/trade_history.html', {
        'annotated_trades': annotated_trades,
        'total_realized_gain': total_realized_gain,
    })


@login_required
def portfolio(request):
    """Show current holdings based on saved trades."""
    trades_cleared = request.GET.get('demo') == 'cleared'
    coach_message = None
    just_analyzed = False

    if request.method == 'POST' and request.POST.get('action') == 'coach':
        latest = CoachAnalysis.objects.filter(user=request.user).first()
        if latest:
            elapsed = (timezone.now() - latest.created_at).total_seconds()
            if elapsed < 60:
                wait = int(60 - elapsed)
                coach_message = ('warning', f"Please wait {wait} more seconds before refreshing.")
                just_analyzed = True
            else:
                result = get_coach_analysis(request.user)
                if not CoachAnalysis.objects.filter(user=request.user).exists():
                    coach_message = ('error', result)
                just_analyzed = True
        else:
            result = get_coach_analysis(request.user)
            if not CoachAnalysis.objects.filter(user=request.user).exists():
                coach_message = ('error', result)
            just_analyzed = True
    trades = Trade.objects.filter(user=request.user).order_by('created_at')
    starting_cash = request.user.profile.starting_balance

    holdings, _, _, total_realized_gain = compute_trade_state(trades, starting_cash=starting_cash)

    total_holdings_value = Decimal('0.00')
    portfolio_rows = []

    for ticker, h in holdings.items():
        shares = h['shares']
        average_cost = h['avg_cost']
        realized_gain = h['realized_gain']
        current_price = None
        total_value = None
        gain_loss = None
        gain_loss_per_share = None
        gain_loss_percent = None

        try:
            stock = yf.Ticker(ticker)
            data = stock.history(period='1d')

            if not data.empty:
                latest_price = round(float(data['Close'].iloc[-1]), 2)
                current_price = Decimal(str(latest_price))
                total_value = shares * current_price
                cost_basis = average_cost * shares
                gain_loss = total_value - cost_basis
                gain_loss_per_share = current_price - average_cost
                if cost_basis > 0:
                    gain_loss_percent = (gain_loss / cost_basis) * Decimal('100')
                total_holdings_value += total_value
        except Exception:
            pass

        portfolio_rows.append({
            'ticker': ticker,
            'shares': shares,
            'average_cost': average_cost,
            'current_price': current_price,
            'total_value': total_value,
            'gain_loss': gain_loss,
            'gain_loss_per_share': gain_loss_per_share,
            'gain_loss_percent': gain_loss_percent,
            'realized_gain': realized_gain,
        })

    cash_balance = request.user.profile.cash_balance
    total_account_value = cash_balance + total_holdings_value
    if starting_cash > 0:
        total_return_percent = (total_account_value - starting_cash) / starting_cash * 100
    else:
        total_return_percent = Decimal('0')

    priced_rows = [r for r in portfolio_rows if r['total_value'] is not None]
    allocation_chart = None
    cost_vs_value_chart = None
    portfolio_history_chart = None

    if priced_rows:
        pie_labels = [r['ticker'] for r in priced_rows] + ['Cash']
        pie_values = [float(r['total_value']) for r in priced_rows] + [float(cash_balance)]
        pie_fig = go.Figure(go.Pie(
            labels=pie_labels,
            values=pie_values,
            hole=0.4,
            textinfo='label+percent',
        ))
        pie_fig.update_layout(
            title='Portfolio Allocation',
            margin=dict(t=50, b=20, l=20, r=20),
            height=350,
        )
        allocation_chart = pie_fig.to_html(full_html=False, include_plotlyjs='cdn')

        gl_rows = [r for r in priced_rows if r['gain_loss'] is not None]
        if gl_rows:
            bar_tickers = [r['ticker'] for r in gl_rows]
            cost_values = [float(r['average_cost'] * r['shares']) for r in gl_rows]
            current_values = [float(r['total_value']) for r in gl_rows]
            current_colors = ['#27ae60' if cv >= bv else '#c0392b'
                              for cv, bv in zip(current_values, cost_values)]
            bar_fig = go.Figure()
            bar_fig.add_trace(go.Bar(
                name='Cost Basis',
                x=bar_tickers,
                y=cost_values,
                marker_color='#6b9fd4',
            ))
            bar_fig.add_trace(go.Bar(
                name='Current Value',
                x=bar_tickers,
                y=current_values,
                marker_color=current_colors,
            ))
            bar_fig.update_layout(
                barmode='group',
                title='Cost Basis vs Current Value',
                yaxis_title='Dollars ($)',
                margin=dict(t=50, b=30, l=20, r=20),
                height=350,
                legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
            )
            cost_vs_value_chart = bar_fig.to_html(full_html=False, include_plotlyjs='cdn')

    try:
        all_trades_list = list(trades)
        hist_dates, hist_values = build_portfolio_history(all_trades_list, starting_cash=starting_cash)
        if hist_dates and hist_values:
            hist_fig = go.Figure()
            hist_fig.add_trace(go.Scatter(
                x=hist_dates,
                y=hist_values,
                mode='lines',
                fill='tozeroy',
                name='Portfolio Value',
                line=dict(color='#0b5cab', width=2),
                fillcolor='rgba(11,92,171,0.1)',
            ))
            hist_fig.add_hline(
                y=float(starting_cash),
                line_dash='dash',
                line_color='#aaa',
                annotation_text='Starting Cash',
                annotation_position='bottom right',
            )
            hist_fig.update_layout(
                title='Portfolio Value Over Time',
                xaxis_title='Date',
                yaxis_title='Value ($)',
                margin=dict(l=40, r=20, t=50, b=40),
                height=380,
            )
            portfolio_history_chart = hist_fig.to_html(full_html=False, include_plotlyjs='cdn')
    except Exception:
        portfolio_history_chart = None

    latest_analysis = CoachAnalysis.objects.filter(user=request.user).first()

    return render(request, 'trading/portfolio.html', {
        'portfolio_rows': portfolio_rows,
        'starting_cash': starting_cash,
        'cash_balance': cash_balance,
        'total_holdings_value': total_holdings_value,
        'total_account_value': total_account_value,
        'total_realized_gain': total_realized_gain,
        'total_return_percent': total_return_percent,
        'trades_cleared': trades_cleared,
        'allocation_chart': allocation_chart,
        'cost_vs_value_chart': cost_vs_value_chart,
        'portfolio_history_chart': portfolio_history_chart,
        'latest_analysis': latest_analysis,
        'coach_message': coach_message,
        'just_analyzed': just_analyzed,
    })


@login_required
def watchlist(request):
    """Show the user's watchlist and allow adding tickers."""
    error_message = None

    if request.method == 'POST':
        ticker = request.POST.get('ticker', '').strip().upper()
        if ticker:
            if len(ticker) > 10:
                error_message = 'Ticker symbols must be 10 characters or fewer.'
            else:
                price = fetch_latest_price(ticker)
                if price is None:
                    error_message = f'"{ticker}" is not a recognised ticker symbol.'
                else:
                    WatchlistItem.objects.get_or_create(user=request.user, ticker=ticker)
                    return redirect('trading:watchlist')
        else:
            return redirect('trading:watchlist')

    items = WatchlistItem.objects.filter(user=request.user).order_by('ticker')
    enriched = []
    for item in items:
        price = fetch_latest_price(item.ticker)
        enriched.append({'ticker': item.ticker, 'price': price, 'added_at': item.added_at})

    return render(request, 'trading/watchlist.html', {'watchlist': enriched, 'error_message': error_message})


@login_required
def remove_from_watchlist(request, ticker):
    """Remove a ticker from the user's watchlist."""
    if request.method == 'POST':
        WatchlistItem.objects.filter(user=request.user, ticker=ticker.upper()).delete()
    return redirect('trading:watchlist')



@login_required
def clear_trades(request):
    """Delete all trades so the app returns to an empty state."""
    if request.method == 'POST':
        Trade.objects.filter(user=request.user).delete()
        profile = request.user.profile
        profile.cash_balance = profile.starting_balance
        profile.save()
        return redirect('/portfolio/?demo=cleared')

    return redirect('trading:index')
