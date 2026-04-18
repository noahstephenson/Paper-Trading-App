# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

This is a Django-based paper trading web application for CY300 (Programming Fundamentals) at West Point. The goal is a **clear, working, and demoable MVP** using **basic Django concepts effectively** — not a production system.

This project should reflect strong understanding of core Django patterns, ability to explain system design in a class setting, and clean, simple, functional implementation.

## Core Philosophy

Prioritize in this order:

1. **Simplicity** over sophistication
2. **Understandability** over optimization
3. **Working functionality** over completeness
4. **Explainability** over cleverness

When there's a tradeoff, choose the version easiest to explain to a professor.

## Tech Stack (Fixed)

- Django, SQLite, yfinance, HTML templates, basic CSS

Do NOT introduce: React, REST APIs, async frameworks, Docker, Celery, Redis, Bootstrap, or complex frontend tooling.

## Django Design Constraints

Use **function-based views**, simple models, simple templates, and straightforward URL routing. Keep logic in `views.py`, `models.py`, and simple helpers only when clearly helpful.

Avoid: class-based views, service layers, custom managers, signals, deep abstraction.

## Dev Commands

```bash
# First-time setup
python -m venv .venv
source .venv/Scripts/activate   # Git Bash on Windows
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser

# Run the app
python manage.py runserver
# App: http://127.0.0.1:8000/
# Admin: http://127.0.0.1:8000/admin/

# Run tests
python manage.py test trading

# Apply model changes
python manage.py makemigrations
python manage.py migrate
```

## Architecture

**Single Django app** (`trading/`) inside a project config package (`config/`).

- `config/settings.py` — project settings, SQLite DB, installed apps
- `config/urls.py` → `trading/urls.py` — URL routing
- `trading/models.py` — one `Trade` model (ForeignKey to User); portfolio computed from trade history, not stored separately
- `trading/views.py` — 7 function-based views covering auth, search, trade flow, portfolio, history
- `trading/templates/trading/` — one template per view; `templates/registration/` for login/register
- `trading/static/trading/styles.css` — all custom styles

## Key Patterns

**Trade confirmation flow**: Step 1 fetches current price from `yfinance` and stores a `pending_trade` dict in `request.session`. Step 2 reads that session, re-validates, saves the `Trade`, and clears the session. GET requests to the confirm step clear stale session data.

**Portfolio calculation**: No portfolio table. Holdings and cash balance are computed at request time by iterating the user's `Trade` queryset — BUYs add shares/subtract cash, SELLs do the reverse. Starting balance is a constant in `views.py`.

**Stock data**: All price lookups go through `yfinance`. Views handle failures gracefully so a bad ticker or API timeout never crashes the page.

**Auth**: Django's built-in system — `@login_required`, `UserCreationForm`, `get_user_model()`. No custom user model.

## Validation Requirements

Must handle: missing ticker, invalid ticker, quantity ≤ 0, invalid trade type, selling more shares than owned. The app must never crash on user input.

## How Claude Should Work on This Project

**Before coding**: explain the goal, why it matters, which files change, and how to test it.

**During coding**: make the smallest possible change; avoid touching unrelated code.

**After coding**: explain what changed, the request/data flow, and what's worth understanding for class.

Always ask: Is this needed for the MVP? Is this the simplest way? Can I explain this easily? If not — simplify.

## Demo Scenarios
- Login as testuser / password123
- Search AAPL, execute a buy
- Search TSLA, attempt to sell more than owned (show validation)
- View portfolio page, explain computed balance