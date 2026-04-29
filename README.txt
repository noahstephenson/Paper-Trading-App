README.txt
===========
Project Title: CY300 Paper Trading App
-------------------------------------------
Author: Cadet Noah Stephenson
Date: April 29, 2026

1. Overview
-----------
This web application lets a user simulate stock trading without using real
money. Users can perform the following tasks:

- Create an account, log in, and log out.
- Search a stock ticker and view live price data and a 30-day price chart.
- Place paper BUY and SELL trades using a two-step confirmation flow that
  shows the fetched price before saving.
- Receive a 1-sentence AI comment on each proposed trade at the review step.
- View a portfolio page showing current holdings, gain/loss metrics, and
  two interactive charts.
- Get a short AI coaching analysis of overall trading activity from the
  portfolio page.
- Save tickers to a watchlist and view past trade history.
- Inspect all saved data through Django admin.

2. Files
--------
- `manage.py`: Django entry point used to run the server, run migrations,
  and run the test suite.
- `trading/views.py`: All function-based views covering auth, search,
  trade flow, portfolio, watchlist, and trade history.
- `trading/models.py`: The Trade and WatchlistItem database models.
- `trading/urls.py`: URL routing for the trading app.
- `trading/forms.py`: Trade form and user registration form.
- `trading/services/market_data.py`: Wrapper around yfinance with a
  5-minute cache to avoid redundant API calls.
- `trading/services/ai_coach.py`: Claude AI integration for the trade
  evaluation comment and portfolio coaching feature.
- `trading/services/portfolio.py`: Helper functions that compute holdings
  and cash balance from the trade history.
- `trading/templates/trading/`: HTML templates, one per page.
- `trading/tests.py`: Automated test suite covering views and models.
- `config/settings.py`: Django project settings (database, installed apps,
  cache, etc.).
- `requirements.txt`: All Python dependencies with pinned versions.
- `.env`: Environment file holding the Django secret key and Anthropic API
  key (not checked into version control).
- `README.txt`: Instructions for running and using the program (this file).

3. Running the Program
----------------------
To run the program:

1. Open Git Bash or a terminal and navigate to the project folder.

2. Create and activate the virtual environment:
      python -m venv .venv
      source .venv/Scripts/activate

3. Install dependencies:
      pip install -r requirements.txt

4. Apply database migrations:
      python manage.py migrate

5. Create an admin user (optional, to access /admin/):
      python manage.py createsuperuser

6. Start the development server:
      python manage.py runserver

7. Open the app in a browser:
      App:   http://127.0.0.1:8000/
      Admin: http://127.0.0.1:8000/admin/

A demo account is available: username testuser / password password123.

4. Dependencies
---------------
The program requires Python 3.10 or higher. Key libraries used:

- `django` (web framework) — install via requirements.txt
- `yfinance` (live stock data) — install via requirements.txt
- `plotly` (interactive charts) — install via requirements.txt
- `anthropic` (Claude AI API) — install via requirements.txt
- `pytest` and `pytest-django` (test suite) — install via requirements.txt

To install all dependencies at once, run:
      pip install -r requirements.txt

The AI features also require an Anthropic API key stored in a `.env` file
at the project root in this format:
      ANTHROPIC_API_KEY=your_key_here

5. Input
--------
The program fetches live stock price data from yfinance automatically when
a user searches a ticker. No user-provided input files are required. The
`.env` file must be present for AI features to work, but the rest of the
app functions without it.

6. Output
---------
All trades are saved to a local SQLite database file (`db.sqlite3`). The
app does not export files. Portfolio data, trade history, and watchlist
entries are all read from this database and displayed in the browser.

7. Contact
----------
If you encounter issues running the program, please contact Cadet
Stephenson at noah.stephenson@westpoint.com.
