# CY300 Paper Trading MVP Diagrams

This folder includes Mermaid diagrams for the current Django paper trading MVP.

The diagrams are intentionally simple and match the app as it exists now:
- Django built-in authentication for login and registration
- one `Trade` model stored in SQLite
- holdings and portfolio values derived from saved trades
- market prices fetched with `yfinance`
- a two-step trade flow where the user submits a trade and then confirms it

Useful diagrams in this folder:
- `app-structure-diagram.mmd` shows the high-level app pieces
- `class-diagram.mmd` shows the real stored data model
- `django-structure.mmd` shows the project file layout
- `mvp-user-flow.mmd` shows the main user workflow
- `page-map.mmd` shows how the pages connect
- `trade-sequence.mmd` shows the trade review and confirm flow
- `use-case-diagram.mmd` shows what the user and admin can do

These diagrams are meant to stay easy to explain in class, so they avoid extra architecture that the MVP does not actually use.
