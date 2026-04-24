import logging
from datetime import timedelta
from decimal import Decimal

import anthropic
import yfinance as yf
from decouple import config
from django.utils import timezone

from ..models import Trade, CoachAnalysis
from .portfolio import compute_trade_state

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an educational trading coach reviewing a student's paper trading portfolio. Give brief, specific feedback based only on the data provided.

Rules:
- Under 80 words total.
- Note one strength and one concern you actually see in the data.
- End with one short question for the student to reflect on.
- Plain language only. No bullet points or headers. No financial advice."""


def build_portfolio_context(user):
    trades = Trade.objects.filter(user=user).order_by('created_at')
    starting_cash = user.profile.starting_balance
    holdings_raw, _, _, _ = compute_trade_state(trades, starting_cash=starting_cash)
    cash_balance = user.profile.cash_balance

    holdings = []
    total_holdings_value = Decimal('0.00')

    for ticker, h in holdings_raw.items():
        shares = h['shares']
        avg_cost = h['avg_cost']
        current_price = avg_cost  # fallback if yfinance fails
        try:
            data = yf.Ticker(ticker).history(period='1d')
            if not data.empty:
                current_price = Decimal(str(round(float(data['Close'].iloc[-1]), 2)))
        except Exception:
            pass
        market_value = shares * current_price
        cost_basis = avg_cost * shares
        gain_loss_pct = float((market_value - cost_basis) / cost_basis * 100) if cost_basis > 0 else 0.0
        total_holdings_value += market_value
        holdings.append({
            'ticker': ticker,
            'quantity': shares,
            'avg_cost': float(avg_cost),
            'current_price': float(current_price),
            'market_value': float(market_value),
            'gain_loss_pct': gain_loss_pct,
        })

    total_portfolio_value = cash_balance + total_holdings_value
    total_return_pct = (
        float((total_portfolio_value - starting_cash) / starting_cash * 100)
        if starting_cash > 0 else 0.0
    )

    concentration = 0.0
    if holdings and total_portfolio_value > 0:
        max_val = max(h['market_value'] for h in holdings)
        concentration = float(max_val / float(total_portfolio_value) * 100)

    recent = Trade.objects.filter(user=user).order_by('-created_at')[:10]
    recent_trades = [
        {
            'ticker': t.ticker,
            'type': t.trade_type,
            'quantity': t.quantity,
            'price': float(t.price),
            'created_at': t.created_at.isoformat(),
            'notes': t.notes or '',
        }
        for t in recent
    ]

    thirty_days_ago = timezone.now() - timedelta(days=30)
    return {
        'cash_balance': float(cash_balance),
        'starting_balance': float(starting_cash),
        'total_portfolio_value': float(total_portfolio_value),
        'total_return_pct': total_return_pct,
        'holdings': holdings,
        'recent_trades': recent_trades,
        'trade_count_total': Trade.objects.filter(user=user).count(),
        'trade_count_30d': Trade.objects.filter(user=user, created_at__gte=thirty_days_ago).count(),
        'concentration': concentration,
    }


def _format_portfolio_for_claude(ctx):
    lines = [
        "Portfolio Overview:",
        f"  Starting balance: ${ctx['starting_balance']:,.2f}",
        f"  Current portfolio value: ${ctx['total_portfolio_value']:,.2f}",
        f"  Total return: {ctx['total_return_pct']:+.2f}%",
        f"  Cash on hand: ${ctx['cash_balance']:,.2f}",
        "",
        f"Current Holdings ({len(ctx['holdings'])} positions):",
    ]
    for h in ctx['holdings']:
        lines.append(
            f"  {h['ticker']} — {h['quantity']} shares | avg cost: ${h['avg_cost']:.2f} | "
            f"current: ${h['current_price']:.2f} | gain: {h['gain_loss_pct']:+.1f}%"
        )
    if not ctx['holdings']:
        lines.append("  (no open positions)")

    lines += ["", f"Recent Trades (last {min(10, ctx['trade_count_total'])}):"]
    for t in ctx['recent_trades']:
        lines.append(
            f"  {t['type']} {t['quantity']} {t['ticker']} @ ${t['price']:.2f} on {t['created_at'][:10]}"
        )

    lines += [
        "",
        f"Activity: {ctx['trade_count_total']} trades total, {ctx['trade_count_30d']} in the last 30 days",
        f"Top position concentration: {ctx['concentration']:.1f}% of portfolio",
    ]
    if ctx['trade_count_total'] < 3:
        lines.append("\nNote: This student has fewer than 3 trades and is just getting started.")
    return "\n".join(lines)


def get_coach_analysis(user):
    api_key = config("ANTHROPIC_API_KEY", default=None)
    if not api_key:
        return "The AI coach is not available yet. (API key not configured.)"

    try:
        context = build_portfolio_context(user)
    except Exception as e:
        logger.error("build_portfolio_context failed: %s", e)
        return "The AI coach is temporarily unavailable. Please try again later."

    user_message = _format_portfolio_for_claude(context)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        analysis_text = message.content[0].text if message.content else ""
        if not analysis_text.strip():
            return "The AI coach returned an empty response. Please try again."

        CoachAnalysis.objects.create(
            user=user,
            portfolio_snapshot=context,
            analysis_text=analysis_text,
        )
        return analysis_text

    except Exception as e:
        logger.error("Anthropic API error: %s", e)
        return "The AI coach is temporarily unavailable. Please try again later."
