# CY300 Paper Trading MVP Diagrams

This folder includes two lightweight Mermaid diagrams for a Django paper trading MVP.

`class-diagram.mmd` shows the main building blocks of the app:
- `User` owns one `Portfolio`
- `Portfolio` holds `Position` records and `Trade` history
- `Trade` changes positions over time
- `MarketDataService` provides ticker checks and current prices from `yfinance`

This matters because it explains what data the app stores and how the core trading pieces fit together without adding extra features that are outside MVP scope.

`trade-sequence.mmd` shows the basic workflow for buying a stock:
- the user submits a buy request
- the Django view/form validates input
- the trade service checks the ticker and current price
- the app checks available cash
- the trade is recorded and the portfolio is updated

This matters because it shows the end-to-end path of a paper trade in a way that is easy to present in class and connect back to the Django app's main responsibilities.
