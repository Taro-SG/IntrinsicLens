# IntrinsicLens

A value investing planner that facilitate a entry/exit plan by estimating company's intrinsic value and risk under the three principles from Graham-Buffet approach: https://intrinsiclens.streamlit.app/

## Run locally

```bash
cd stock-analysis
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Enter a ticker such as `AAPL`, `MSFT`, or `COST`, or type a company name and choose a matching symbol from the suggestions. The app shows the latest available price, trailing P/E, 52-week range, balance-sheet assets and debt, assets-to-debt and assets-to-liabilities ratios, and the largest peak-to-trough decline in available 10-year adjusted-price history.

## Value-investing lenses

- **Mr. Market:** Inspect price swings over one, three, or five years. The chart illustrates volatility; it does not determine whether a stock is cheap.
- **Margin of safety:** Enter your own per-share value estimate and choose a cushion. The app calculates `your estimate × (1 − cushion)`; it does not produce or validate an intrinsic-value estimate.
- **Graham estimates:** The Graham Number uses average annual EPS and book value per share. The updated intrinsic-value formula uses latest annual EPS and your manually entered expected growth rate (`g`) and current 20-year AAA corporate bond yield (`Y`): `EPS × (8.5 + 2g) × 4.4 ÷ Y`. Enter `g` and `Y` as percentage numbers (for example, `5` for 5%). The yield is not automatically updated.
- **Business ownership:** Review annual revenue, revenue growth, operating margin, and net income, alongside questions about the underlying business.

## Data notes

Market and company data are fetched with [yfinance](https://ranaroussi.github.io/yfinance/), which accesses Yahoo Finance data and is not an official Yahoo Finance product. Data may be delayed, incomplete, or temporarily unavailable. Fundamentals and historical coverage vary across securities. Historical calculations are informational and are not investment advice.

The live chat room shares messages between sessions connected to the same app server. It stores the 1,000 most recent messages in `intrinsiclens_chat.sqlite3` beside `app.py`; display names are not authenticated.
