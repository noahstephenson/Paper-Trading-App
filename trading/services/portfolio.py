from decimal import Decimal

from ..models import Trade

STARTING_CASH = Decimal('100000.00')


def compute_trade_state(trades, starting_cash=STARTING_CASH):
    """
    Process trades in chronological order and compute full account state.

    Returns:
        holdings: {ticker: {shares, avg_cost, realized_gain}} — only tickers with shares > 0
        annotated_trades: [{trade, running_cash, realized_gain}] — chronological order
        cash_balance: Decimal final cash
        total_realized_gain: Decimal sum of all realized gains
    """
    cash = starting_cash
    state = {}    # ticker → {shares: int, total_cost: Decimal}
    realized = {} # ticker → Decimal
    annotated = []

    for trade in sorted(trades, key=lambda t: t.created_at):
        ticker = trade.ticker
        qty = trade.quantity
        price = trade.price

        if ticker not in state:
            state[ticker] = {'shares': 0, 'total_cost': Decimal('0.00')}

        t_realized = None
        if trade.trade_type == Trade.BUY:
            state[ticker]['shares'] += qty
            state[ticker]['total_cost'] += qty * price
            cash -= qty * price
        else:  # SELL
            s = state[ticker]
            avg = s['total_cost'] / Decimal(s['shares']) if s['shares'] > 0 else price
            t_realized = Decimal(qty) * (price - avg)
            s['total_cost'] -= avg * qty
            s['shares'] -= qty
            realized[ticker] = realized.get(ticker, Decimal('0.00')) + t_realized
            cash += qty * price

        annotated.append({
            'trade': trade,
            'running_cash': cash,
            'realized_gain': t_realized,
        })

    holdings = {}
    for ticker, s in state.items():
        if s['shares'] > 0:
            holdings[ticker] = {
                'shares': s['shares'],
                'avg_cost': s['total_cost'] / Decimal(s['shares']),
                'realized_gain': realized.get(ticker, Decimal('0.00')),
            }

    total_realized = sum(realized.values(), Decimal('0.00'))
    return holdings, annotated, cash, total_realized
