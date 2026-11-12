import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf


st.set_page_config(page_title="IntrinsicLens", page_icon="◉", layout="wide")
CHAT_DB_PATH = Path(__file__).with_name("intrinsiclens_chat.sqlite3")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.stApp { background: #f5f6f3; }
[data-testid="stHeader"] { background: transparent; }
.eyebrow { color:#6f806c; letter-spacing:.14em; font:500 11px 'DM Mono',monospace; text-transform:uppercase; }
.hero { padding: 1.2rem 0 .3rem; }
.hero h1 { font-size: clamp(2.2rem, 4vw, 3.2rem); letter-spacing:-.055em; line-height:1.05; margin:.35rem 0 .5rem; color:#18251d; }
.hero p { color:#68736b; font-size:1.02rem; margin:0; }
.metric-card { background:#fff; border:1px solid #e6e9e3; border-radius:14px; padding:18px 20px; min-height:112px; }
.metric-label { color:#778178; font-size:12px; margin-bottom:10px; }
.metric-value { color:#19261f; font:500 25px 'DM Mono',monospace; letter-spacing:-.04em; }
.metric-note { color:#879087; font-size:11px; margin-top:7px; }
.principle-banner { height:64px; box-sizing:border-box; overflow:hidden; margin:0 0 16px; border:1px solid #dce8dc; border-radius:14px; background:linear-gradient(110deg,#edf4eb,#f8f8f2); color:#263c2c; }
.principle-track { display:flex; width:400%; height:100%; animation:principle-slide 39s infinite linear; }
.principle-slide { flex:0 0 25%; box-sizing:border-box; display:flex; align-items:center; justify-content:center; padding:12px 20px; text-align:center; font-size:clamp(14px,2vw,18px); font-weight:600; letter-spacing:-.02em; }
.extrema-summary { display:flex; flex-wrap:wrap; gap:9px; margin:2px 0 10px; }
.extrema-pill { display:inline-flex; align-items:center; gap:9px; padding:7px 12px; border:1px solid; border-radius:10px; font:500 12px 'DM Mono',monospace; }
.extrema-pill.peak { color:#315f3b; background:#edf5ed; border-color:#cfe0cf; }
.extrema-pill.bottom { color:#174e9a; background:#edf4ff; border-color:#bdd4f4; }
.extrema-label { font-size:10px; font-weight:600; letter-spacing:.08em; }
div[data-testid="stButton"] button[kind="secondary"] { text-align:left; justify-content:flex-start; border-radius:0; border:0; border-bottom:1px solid #e4e8eb; background:#fff; color:#26313b; padding:12px 14px; }
div[data-testid="stButton"] button[kind="secondary"]:hover { background:#e8f3ff; color:#175eb5; border-color:#d4e4f5; }
@keyframes principle-slide {
  0%, 17.949% { transform:translateX(0); animation-timing-function:cubic-bezier(.4,0,.2,1); }
  33.333% { transform:translateX(-25%); }
  51.282% { transform:translateX(-25%); animation-timing-function:cubic-bezier(.4,0,.2,1); }
  66.667% { transform:translateX(-50%); }
  84.615% { transform:translateX(-50%); animation-timing-function:cubic-bezier(.4,0,.2,1); }
  100% { transform:translateX(-75%); }
}
@media (prefers-reduced-motion: reduce) {
  .principle-banner { height:auto; overflow:visible; }
  .principle-track { display:block; width:100%; height:auto; animation:none; }
  .principle-slide { display:flex; min-height:48px; }
  .principle-slide:last-child { display:none; }
}
div[data-testid="stVerticalBlock"] div[data-testid="stHorizontalBlock"] { gap: 12px; }
</style>
""", unsafe_allow_html=True)


def money(value, currency="USD"):
    if value is None or pd.isna(value):
        return "—"
    return f"{currency} {value:,.2f}"


def finite_number(*values):
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return None


def compact(value, currency="USD"):
    if value is None or pd.isna(value):
        return "—"
    magnitude = abs(value)
    if magnitude >= 1e12:
        return f"{currency} {value / 1e12:,.2f}T"
    if magnitude >= 1e9:
        return f"{currency} {value / 1e9:,.2f}B"
    if magnitude >= 1e6:
        return f"{currency} {value / 1e6:,.2f}M"
    return f"{currency} {value:,.0f}"


def ratio(value):
    return "—" if value is None or pd.isna(value) else f"{value:.2f}×"


def statement_value(statement, names):
    if statement is None or statement.empty:
        return None
    row = next((name for name in names if name in statement.index), None)
    if row is None:
        return None
    values = statement.loc[row].dropna()
    return values.iloc[0] if not values.empty else None


def add_high_low_markers(fig, prices, currency):
    high_date = prices["Close"].idxmax()
    low_date = prices["Close"].idxmin()
    fig.add_trace(go.Scatter(
        x=[high_date, low_date],
        y=[prices.loc[high_date, "Close"], prices.loc[low_date, "Close"]],
        mode="markers",
        text=["Peak close", "Bottom close"],
        marker=dict(color=["#5c8655", "#2f6bce"], size=12, line=dict(color="#ffffff", width=2)),
        showlegend=False,
        hovertemplate="%{text}<br>%{x|%b %d, %Y}<br>" + currency + " %{y:,.2f}<extra></extra>",
    ))
    chart_low = prices["Close"].min()
    chart_high = prices["Close"].max()
    padding = (chart_high - chart_low) * 0.12 or abs(chart_high) * 0.05 or 1
    fig.update_yaxes(range=[chart_low - padding, chart_high + padding])
    return fig


def show_extrema_summary(peak_value, peak_date, bottom_value, bottom_date, currency):
    st.markdown(
        f"<div class='extrema-summary'>"
        f"<span class='extrema-pill peak'><span class='extrema-label'>PEAK CLOSE</span><span>{money(peak_value, currency)} · {peak_date.strftime('%b %d, %Y')}</span></span>"
        f"<span class='extrema-pill bottom'><span class='extrema-label'>BOTTOM CLOSE</span><span>{money(bottom_value, currency)} · {bottom_date.strftime('%b %d, %Y')}</span></span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def average_annual_eps(financials, years=5):
    """Average the most recent available annual EPS observations."""
    if financials is None or financials.empty:
        return None, 0, None

    for row in ["Diluted EPS", "Basic EPS"]:
        if row in financials.index:
            eps_values = financials.loc[row].dropna().sort_index(ascending=False).head(years)
            if not eps_values.empty:
                return float(eps_values.mean()), len(eps_values), row

    income_row = next((row for row in ["Net Income Common Stockholders", "Net Income"] if row in financials.index), None)
    shares_row = next((row for row in ["Diluted Average Shares", "Basic Average Shares"] if row in financials.index), None)
    if income_row and shares_row:
        eps_values = (financials.loc[income_row] / financials.loc[shares_row]).replace([float("inf"), -float("inf")], pd.NA).dropna()
        eps_values = eps_values.sort_index(ascending=False).head(years)
        if not eps_values.empty:
            return float(eps_values.mean()), len(eps_values), "derived EPS"
    return None, 0, None


def latest_annual_eps(financials):
    if financials is None or financials.empty:
        return None, None
    for row in ["Diluted EPS", "Basic EPS"]:
        if row in financials.index:
            values = financials.loc[row].dropna().sort_index(ascending=False)
            if not values.empty:
                return float(values.iloc[0]), row
    income_row = next((row for row in ["Net Income Common Stockholders", "Net Income"] if row in financials.index), None)
    shares_row = next((row for row in ["Diluted Average Shares", "Basic Average Shares"] if row in financials.index), None)
    if income_row and shares_row:
        eps = (financials.loc[income_row] / financials.loc[shares_row]).replace([float("inf"), -float("inf")], pd.NA).dropna()
        eps = eps.sort_index(ascending=False)
        if not eps.empty:
            return float(eps.iloc[0]), "derived EPS"
    return None, None


@st.cache_data(ttl=1800, show_spinner=False)
def find_ticker_suggestions(query):
    search = yf.Search(
        query,
        max_results=8,
        news_count=0,
        lists_count=0,
        include_cb=False,
        include_nav_links=False,
        include_research=False,
    )
    suggestions = []
    seen = set()
    for quote in search.quotes or []:
        ticker = quote.get("symbol")
        quote_type = quote.get("quoteType")
        if not ticker or ticker in seen or (quote_type and quote_type not in {"EQUITY", "ETF"}):
            continue
        seen.add(ticker)
        suggestions.append({
            "symbol": ticker,
            "name": quote.get("shortname") or quote.get("longname") or ticker,
            "exchange": quote.get("exchDisp") or quote.get("exchange") or "",
        })
    return suggestions


def choose_ticker(symbol):
    st.session_state["symbol"] = symbol
    st.session_state["ticker_query"] = ""


@st.cache_resource
def initialize_chat_db():
    with sqlite3.connect(CHAT_DB_PATH, timeout=5) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nickname TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
    return True


@st.cache_data(ttl=3, show_spinner=False)
def load_chat_messages():
    with sqlite3.connect(CHAT_DB_PATH, timeout=5) as connection:
        rows = connection.execute("""
            SELECT nickname, message, created_at
            FROM chat_messages
            ORDER BY id DESC
            LIMIT 50
        """).fetchall()
    return [dict(nickname=row[0], message=row[1], created_at=row[2]) for row in reversed(rows)]


def post_chat_message():
    nickname = st.session_state.get("chat_nickname", "").strip()[:32] or "Guest"
    message = st.session_state.get("chat_message", "").strip()[:500]
    now = time.monotonic()
    previous_post = st.session_state.get("chat_last_post", 0)
    if not message:
        st.session_state["chat_feedback"] = "Write a message before sending."
        return
    if now - previous_post < 1.5:
        st.session_state["chat_feedback"] = "Please wait a moment before sending another message."
        return

    with sqlite3.connect(CHAT_DB_PATH, timeout=5) as connection:
        connection.execute(
            "INSERT INTO chat_messages (nickname, message, created_at) VALUES (?, ?, ?)",
            (nickname, message, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        connection.execute("DELETE FROM chat_messages WHERE id NOT IN (SELECT id FROM chat_messages ORDER BY id DESC LIMIT 1000)")
    st.session_state["chat_last_post"] = now
    st.session_state["chat_feedback"] = "Message sent."
    load_chat_messages.clear()


@st.fragment(run_every="3s")
def live_chat_room():
    initialize_chat_db()
    st.divider()
    st.markdown("#### Live chat room")
    st.caption("Messages are shared with people using this same app server and stored on its local disk. Choose a display name; there are no user accounts.")

    if "chat_nickname" not in st.session_state:
        st.session_state["chat_nickname"] = "Guest"
    st.text_input("Display name", max_chars=32, key="chat_nickname")

    feedback = st.session_state.pop("chat_feedback", None)
    if feedback:
        st.caption(feedback)

    with st.container(height=360, border=True):
        messages = load_chat_messages()
        if not messages:
            st.info("No messages yet. Start the conversation.")
        else:
            for item in messages:
                with st.chat_message("user"):
                    st.caption(f"{item['nickname']} · {item['created_at'][:16].replace('T', ' ')} UTC")
                    st.text(item["message"])

    with st.form("intrinsiclens_chat_form", clear_on_submit=True):
        st.text_input("Message", placeholder="Write a message…", max_chars=500, key="chat_message")
        st.form_submit_button("Send", type="primary", on_click=post_chat_message)


@st.cache_data(ttl=900, show_spinner=False)
def load_data(symbol):
    stock = yf.Ticker(symbol)
    history = stock.history(period="max", auto_adjust=True)
    history = history.dropna(subset=["Close"])
    if history.empty:
        raise ValueError("No price history was found for that symbol.")
    try:
        info = stock.info or {}
    except Exception:
        info = {}
    try:
        balance = stock.balance_sheet
    except Exception:
        balance = pd.DataFrame()
    try:
        financials = stock.financials
    except Exception:
        financials = pd.DataFrame()
    return history, info, balance, financials


@st.cache_data(ttl=300, show_spinner=False)
def load_intraday_history(symbol, period):
    interval = {"1D": "5m", "5D": "15m"}[period]
    intraday = yf.Ticker(symbol).history(period=period.lower(), interval=interval, auto_adjust=True)
    if intraday.empty:
        return intraday
    return intraday.dropna(subset=["Close"])


@st.cache_data(ttl=900, show_spinner=False)
def scan_ticker_list(symbols):
    results = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            history = ticker.history(period="5d", interval="1d", auto_adjust=True)
            closes = history["Close"].dropna().astype(float) if not history.empty and "Close" in history else pd.Series(dtype=float)
            price = finite_number(info.get("regularMarketPrice"), info.get("currentPrice"), closes.iloc[-1] if not closes.empty else None)
            previous_close = finite_number(info.get("regularMarketPreviousClose"), closes.iloc[-2] if len(closes) >= 2 else None)
            day_change = finite_number((price / previous_close - 1) * 100) if price is not None and previous_close else None
            volume_values = history["Volume"].dropna() if not history.empty and "Volume" in history else pd.Series(dtype=float)
            volume = finite_number(info.get("regularMarketVolume"), volume_values.iloc[-1] if not volume_values.empty else None)
            market_cap = finite_number(info.get("marketCap"))
            trailing_pe = finite_number(info.get("trailingPE"))
            results.append({
                "Ticker": symbol,
                "Company": info.get("shortName") or info.get("longName") or symbol,
                "Price": price,
                "Day change (%)": day_change,
                "Volume": volume,
                "Market cap ($B)": market_cap / 1e9 if market_cap is not None else None,
                "Trailing P/E": trailing_pe,
                "Status": "OK" if price is not None else "Price unavailable",
            })
        except Exception:
            results.append({
                "Ticker": symbol,
                "Company": symbol,
                "Price": None,
                "Day change (%)": None,
                "Volume": None,
                "Market cap ($B)": None,
                "Trailing P/E": None,
                "Status": "Data unavailable",
            })
    return results


st.markdown("""
<div class="principle-banner">
  <div class="principle-track">
    <div class="principle-slide">Treat Mr. Market as your servant, not your guide.</div>
    <div class="principle-slide">Treat investing as buying businesses, not trading ticker symbols.</div>
    <div class="principle-slide">Margin of Safety.</div>
    <div class="principle-slide">Treat Mr. Market as your servant, not your guide.</div>
  </div>
</div>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="eyebrow">A clearer look at a company</div>
  <h1>IntrinsicLens</h1>
  <p>Enter a ticker to explore its price history and core financials.</p>
</div>
""", unsafe_allow_html=True)

col_search, col_submit = st.columns([5, 1])
with col_search:
    ticker_query = st.text_input("Ticker or company name", placeholder="Try AAPL, MSFT, or Google", label_visibility="collapsed", key="ticker_query").strip()
with col_submit:
    st.button("Analyze →", type="primary", use_container_width=True, disabled=not ticker_query, on_click=choose_ticker, args=(ticker_query.upper(),))

if len(ticker_query) >= 2:
    try:
        ticker_suggestions = find_ticker_suggestions(ticker_query)
    except Exception:
        ticker_suggestions = []
        st.caption("Company search is temporarily unavailable. You can still analyze a ticker directly.")
    if ticker_suggestions:
        with st.container(border=True):
            for index, suggestion in enumerate(ticker_suggestions[:6]):
                label = f"**{suggestion['symbol']}**  ·  {suggestion['name']}"
                if suggestion["exchange"]:
                    label += f"  ·  {suggestion['exchange']}"
                st.button(label, key=f"ticker_suggestion_{index}_{suggestion['symbol']}_{ticker_query}", use_container_width=True, on_click=choose_ticker, args=(suggestion["symbol"],))
    else:
        st.caption("No matches found. You can still analyze the entered ticker directly.")

if "symbol" not in st.session_state:
    st.markdown("""
    <div style="margin-top:1.2rem;padding:22px 24px;background:#edf1e9;border:1px solid #dce8dc;border-radius:14px;color:#586557">
      <span class="eyebrow">Start here</span>
      <h3 style="margin:8px 0 4px;color:#1b3024">IntrinsicLens</h3>
      <p style="margin:0 0 18px;color:#586557"><strong>All-in-one intrinsic value calculator</strong> for estimating <strong>intrinsic value</strong> and <strong>buy-in price</strong> with individualized <strong>margin of safety</strong>.</p>
      <div style="font-weight:600;color:#1b3024;margin-bottom:10px">Three quick steps</div>
      <ol style="margin:0;padding-left:22px;display:grid;gap:8px;color:#586557">
        <li>Use the “Updated intrinsic value estimate” to estimate intrinsic value for your business.</li>
        <li>Plug the estimated value into “Your estimate of intrinsic value per share” under Margin of Safety.</li>
        <li>Apply your margin of safety to estimate your entry price.</li>
      </ol>
    </div>
    """, unsafe_allow_html=True)
    live_chat_room()
    st.stop()

symbol = st.session_state["symbol"]
try:
    with st.spinner(f"Loading {symbol}…"):
        history, info, balance, financials = load_data(symbol)
except Exception as error:
    st.error(f"Could not load {symbol}. Check the ticker and try again. ({error})")
    st.stop()

name = info.get("shortName") or info.get("longName") or symbol
currency = info.get("currency", "USD")
last_price = finite_number(info.get("currentPrice"), info.get("regularMarketPrice"), history["Close"].iloc[-1])
close_prices = history["Close"].dropna().astype(float)
change = finite_number((close_prices.iloc[-1] / close_prices.iloc[-2] - 1) * 100) if len(close_prices) > 1 and close_prices.iloc[-2] else None
now = pd.Timestamp.now(tz=history.index.tz)
one_year = history.loc[history.index >= now - pd.Timedelta(days=365)]
year_high = info.get("fiftyTwoWeekHigh") or (one_year["High"].max() if not one_year.empty else None)
year_low = info.get("fiftyTwoWeekLow") or (one_year["Low"].min() if not one_year.empty else None)
ten_year_history = history.loc[history.index >= now - pd.Timedelta(days=3650)]
if ten_year_history.empty:
    ten_year_history = history
drawdown = ten_year_history["Close"] / ten_year_history["Close"].cummax() - 1
max_decline = drawdown.min() * 100
dd_end = drawdown.idxmin()
dd_start = ten_year_history.loc[:dd_end, "Close"].idxmax()

average_eps, eps_years, eps_basis = average_annual_eps(financials)
latest_eps, latest_eps_basis = latest_annual_eps(financials)
equity = statement_value(balance, ["Stockholders Equity", "Total Stockholder Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"])
if equity is None:
    assets_for_equity = statement_value(balance, ["Total Assets"])
    liabilities_for_equity = statement_value(balance, ["Total Liabilities Net Minority Interest", "Total Liabilities"])
    if assets_for_equity is not None and liabilities_for_equity is not None:
        equity = assets_for_equity - liabilities_for_equity
shares_outstanding = info.get("sharesOutstanding")
book_value_per_share = equity / shares_outstanding if equity is not None and shares_outstanding else None
graham_number = math.sqrt(22.5 * average_eps * book_value_per_share) if average_eps is not None and book_value_per_share is not None and average_eps > 0 and book_value_per_share > 0 else None

st.markdown(f"<div style='margin:1.4rem 0 1rem'><span class='eyebrow'>{symbol}</span><h2 style='margin:.2rem 0;color:#1b2a20'>{name}</h2><span style='color:#728076'>{info.get('sector','')}{' · ' if info.get('sector') and info.get('industry') else ''}{info.get('industry','')}</span></div>", unsafe_allow_html=True)

cards = st.columns(4)
metrics = [
    ("Latest price", money(last_price, currency), f"{change:+.2f}% latest session" if change is not None else "Session change unavailable"),
    ("P/E ratio", ratio(info.get("trailingPE")), "Trailing twelve months"),
    ("52-week range", f"{money(year_low, currency)} – {money(year_high, currency)}", "Reported or observed range"),
    ("10-year max decline", f"{max_decline:.1f}%", f"Peak {dd_start.strftime('%b %Y')} → bottom {dd_end.strftime('%b %Y')}"),
]
for col, (label, value, note) in zip(cards, metrics):
    with col:
        size = "20px" if label == "52-week range" else "25px"
        st.markdown(f"<div class='metric-card'><div class='metric-label'>{label}</div><div class='metric-value' style='font-size:{size}'>{value}</div><div class='metric-note'>{note}</div></div>", unsafe_allow_html=True)

st.divider()
st.markdown("#### Updated intrinsic value estimate")
st.caption("V = [EPS × (8.5 + 2g) × 4.4] ÷ Y. EPS uses the latest reported annual figure; enter g and Y as percentage numbers (for example, 5 means 5%).")
assumption_cols = st.columns([1, 1, 1.25])
assumption_cols[0].metric("Latest annual EPS", f"{currency} {latest_eps:.2f}" if latest_eps is not None else "—", latest_eps_basis or "Not reported")
with assumption_cols[1]:
    growth_text = st.text_input("Expected annual EPS growth, g (%)", placeholder="e.g. 5", key=f"graham_growth_{symbol}")
    encoded_symbol = quote(symbol, safe="")
    sec_10k_url = f"https://www.sec.gov/edgar/search/#/q={encoded_symbol}&dateRange=all&category=custom&forms=10-K"
    sec_8k_url = f"https://www.sec.gov/edgar/search/#/q={encoded_symbol}&dateRange=all&category=custom&forms=8-K"
    st.markdown(f"[Latest SEC 10-K ↗]({sec_10k_url}) · [Latest SEC 8-K ↗]({sec_8k_url})")
with assumption_cols[2]:
    yield_text = st.text_input("Current 20-year AAA yield, Y (%)", placeholder="Enter current yield", key=f"graham_yield_{symbol}")

try:
    growth_rate = float(growth_text.replace(",", "").strip()) if growth_text.strip() else None
except ValueError:
    growth_rate = None
    st.warning("Enter a numeric growth rate for g.")
try:
    aaa_yield = float(yield_text.replace(",", "").strip()) if yield_text.strip() else None
except ValueError:
    aaa_yield = None
    st.warning("Enter a numeric current yield for Y.")

if latest_eps is not None and latest_eps > 0 and growth_rate is not None and aaa_yield is not None and aaa_yield > 0 and 8.5 + 2 * growth_rate > 0:
    intrinsic_estimate = latest_eps * (8.5 + 2 * growth_rate) * 4.4 / aaa_yield
    result_col, comparison_col = st.columns(2)
    result_col.metric("Updated intrinsic value estimate", money(intrinsic_estimate, currency))
    comparison_col.metric("Estimate vs. latest price", f"{(intrinsic_estimate / last_price - 1) * 100:+.1f}%")
elif growth_rate is not None and aaa_yield is not None:
    st.warning("This calculation requires positive reported EPS, a positive bond yield, and a positive growth multiplier (8.5 + 2g).")
else:
    st.info("Enter an expected EPS growth rate and the current 20-year AAA corporate bond yield to calculate this estimate. The yield is a manual input and is not live-updated.")

st.divider()
st.markdown("#### Three value-investing lenses")
st.caption("Use these illustrations to structure your own analysis. They are not a buy/sell signal, and the app does not know your estimate of a business’s value.")
safety_tab, business_tab, market_tab = st.tabs(["01 · Margin of Safety", "02 · Business Fundamentals", "03 · Mr. Market"])

with market_tab:
    st.markdown("##### Treat price swings as offers, not instructions")
    market_period = st.segmented_control(
        "Price history to inspect",
        ["YTD", "3 months", "6 months", "1 Year", "2 years", "3 years", "5 years", "10 years", "All time"],
        default="3 years",
        key="market_period",
    ) or "3 years"
    if market_period == "All time":
        market_history = history
    else:
        market_start = pd.Timestamp(year=now.year, month=1, day=1, tz=history.index.tz) if market_period == "YTD" else now - pd.Timedelta(days={"3 months": 90, "6 months": 182, "1 Year": 365, "2 years": 365 * 2, "3 years": 365 * 3, "5 years": 365 * 5, "10 years": 3650}[market_period])
        market_history = history.loc[history.index >= market_start]
    market_closes = market_history["Close"].dropna().astype(float)
    recent_peak = market_closes.cummax().iloc[-1] if not market_closes.empty else None
    market_decline = finite_number((market_closes.iloc[-1] / recent_peak - 1) * 100) if recent_peak else None
    market_high = market_history["Close"].max()
    market_low = market_history["Close"].min()
    m1, m2, m3 = st.columns(3)
    m1.metric("Latest price", money(last_price, currency))
    m2.metric(f"{market_period} peak close", money(market_high, currency))
    m3.metric("Below recent peak", f"{market_decline:.1f}%" if market_decline is not None else "—")
    market_peak_date = market_history["Close"].idxmax()
    market_bottom_date = market_history["Close"].idxmin()
    show_extrema_summary(market_high, market_peak_date, market_low, market_bottom_date, currency)
    market_fig = go.Figure(go.Scatter(x=market_history.index, y=market_history["Close"], mode="lines", line=dict(color="#5c8655", width=2), fill="tozeroy", fillcolor="rgba(92,134,85,.09)", hovertemplate="%{x|%b %d, %Y}<br>" + currency + " %{y:,.2f}<extra></extra>"))
    add_high_low_markers(market_fig, market_history, currency)
    market_fig.add_hline(y=last_price, line_dash="dot", line_color="#99a696", annotation_text="Latest price", annotation_position="top left")
    market_fig.update_layout(height=330, margin=dict(l=5, r=5, t=8, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#778178", size=11), xaxis=dict(showgrid=False, linecolor="#e6e9e3"), yaxis=dict(title=None, gridcolor="#e9ece7", side="right", tickprefix=currency + " "), hovermode="x unified")
    st.plotly_chart(market_fig, use_container_width=True, config={"displayModeBar": False})
    st.info(f"Over this window, {symbol}'s closing prices ranged from {money(market_low, currency)} to {money(market_high, currency)}. A falling quote alone does not tell you whether the business is cheaper than its value; investigate what changed in the business.")

with safety_tab:
    estimate_text = st.text_input("Your estimate of intrinsic value per share", placeholder=f"Enter an amount in {currency}", key=f"intrinsic_value_{symbol}")
    mos_columns = st.columns(2)
    with mos_columns[0]:
        mos = st.slider("Margin of safety (negative = premium)", min_value=-100, max_value=100, value=0, step=1, format="%d%%")
    try:
        intrinsic_value = float(estimate_text.replace(",", "").strip()) if estimate_text.strip() else None
        if intrinsic_value is not None and intrinsic_value <= 0:
            intrinsic_value = None
    except ValueError:
        intrinsic_value = None
        st.warning("Enter a positive number to see the illustration.")
    if intrinsic_value:
        buy_below = intrinsic_value * (1 - mos / 100)
        discount = (intrinsic_value / last_price - 1) * 100
        price_level_label = f"Illustrative price with {mos}% cushion" if mos >= 0 else f"Illustrative price at {abs(mos)}% premium"
        s1, s2, s3 = st.columns(3)
        s1.metric("Your value estimate", money(intrinsic_value, currency))
        s2.metric(price_level_label, money(buy_below, currency))
        s3.metric("Price vs. your estimate", f"{discount:+.1f}%", help="Positive means the latest price is below your estimate; negative means it is above.")
        if mos < 0 and last_price <= intrinsic_value:
            st.info("The latest price is below your value estimate. A negative setting describes a premium you would allow above that estimate; it is not a margin of safety.")
        elif mos < 0 and last_price <= buy_below:
            st.warning("The latest price is above your value estimate but within the selected premium level. This does not provide a margin of safety.")
        elif mos < 0:
            st.error("The latest price is above both your value estimate and the selected premium level.")
        elif last_price <= buy_below:
            st.success(f"At the latest quote, the price is at or below your illustrative {mos}% cushion level. This only compares your input with the market price; it does not validate your valuation assumptions.")
        else:
            st.info(f"The latest quote is above your illustrative cushion level of {money(buy_below, currency)}. Revisit the assumptions or wait; the calculation is only as sound as your estimate.")
    else:
        st.info("Enter your own per-share value estimate above. The app will calculate a price level with the selected cushion; it will not create an intrinsic-value estimate for you.")
    st.caption("Illustration: price level = your intrinsic-value estimate × (1 − margin of safety). A negative percentage raises the price level above your estimate; it represents a premium, not a cushion. This is simple arithmetic, not a valuation model.")

with business_tab:
    st.markdown("##### Look through the ticker to the company")
    revenue = statement_value(financials, ["Total Revenue"])
    operating_income = statement_value(financials, ["Operating Income"])
    net_income = statement_value(financials, ["Net Income", "Net Income Common Stockholders"])
    revenues = financials.loc["Total Revenue"].dropna().sort_index() if financials is not None and not financials.empty and "Total Revenue" in financials.index else pd.Series(dtype=float)
    revenue_growth = (revenues.iloc[-1] / revenues.iloc[-2] - 1) * 100 if len(revenues) >= 2 and revenues.iloc[-2] else None
    operating_margin = operating_income / revenue * 100 if operating_income is not None and revenue else None
    b1, b2, b3 = st.columns(3)
    b1.metric("Latest annual revenue", compact(revenue, currency))
    b2.metric("Latest annual revenue growth", f"{revenue_growth:+.1f}%" if revenue_growth is not None else "—")
    b3.metric("Latest operating margin", f"{operating_margin:.1f}%" if operating_margin is not None else "—")
    st.caption(f"Latest reported net income: {compact(net_income, currency)}. Annual statement figures vary by provider; compare multiple years and read the filings for context.")
    st.markdown("**Questions to ask about the business**")
    q1, q2, q3 = st.columns(3)
    q1.markdown("Can I explain what it sells, who pays, and why customers return?")
    q2.markdown("Are revenue and profits durable across different conditions?")
    q3.markdown("Does it have an advantage, and can it fund growth without excessive debt?")

st.divider()
st.markdown("#### Graham Number")
st.caption("A traditional rule-of-thumb price estimate: √(22.5 × average annual EPS × book value per share). Uses up to five reported fiscal years and the latest reported equity; it is not a full valuation model.")
graham_cols = st.columns(3)
graham_cols[0].metric("Average annual EPS", f"{currency} {average_eps:.2f}" if average_eps is not None else "—", f"{eps_years} year(s), {eps_basis}" if average_eps is not None else "Not reported")
graham_cols[1].metric("Book value per share", money(book_value_per_share, currency), "Latest equity ÷ shares outstanding")
graham_cols[2].metric("Graham Number", money(graham_number, currency), "Shown only when both inputs are positive")

st.divider()
chart_col, side_col = st.columns([1.7, 1])
with chart_col:
    st.markdown("#### Price history")
    period = st.segmented_control("Period", ["1D", "5D", "1M", "6M", "YTD", "1Y", "5Y", "All"], default="1Y", label_visibility="collapsed") or "1Y"
    if period in {"1D", "5D"}:
        view = load_intraday_history(symbol, period)
    elif period == "All":
        view = history
    elif period == "YTD":
        year_start = pd.Timestamp(year=now.year, month=1, day=1, tz=history.index.tz)
        view = history.loc[history.index >= year_start]
    else:
        days = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 365 * 5}[period]
        view = history.loc[history.index >= now - pd.Timedelta(days=days)]

    if view.empty:
        st.info(f"Price history for {period} is not available from the data provider right now.")
    else:
        view = view.dropna(subset=["Close"])
        price_peak_date = view["Close"].idxmax()
        price_bottom_date = view["Close"].idxmin()
        show_extrema_summary(view.loc[price_peak_date, "Close"], price_peak_date, view.loc[price_bottom_date, "Close"], price_bottom_date, currency)
        fig = go.Figure(go.Scatter(x=view.index, y=view["Close"], mode="lines", line=dict(color="#5c8655", width=2), fill="tozeroy", fillcolor="rgba(92,134,85,.09)", hovertemplate="%{x|%b %d, %Y}<br>" + currency + " %{y:,.2f}<extra></extra>"))
        add_high_low_markers(fig, view, currency)
        fig.update_layout(height=330, margin=dict(l=5, r=5, t=8, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#778178", size=11), xaxis=dict(showgrid=False, linecolor="#e6e9e3"), yaxis=dict(title=None, gridcolor="#e9ece7", side="right", tickprefix=currency + " "), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
with side_col:
    st.markdown("#### Balance sheet")
    st.caption("Most recent reported period")
    total_assets = statement_value(balance, ["Total Assets"]) or info.get("totalAssets")
    total_debt = statement_value(balance, ["Total Debt", "Long Term Debt"]) or info.get("totalDebt")
    total_liabilities = statement_value(balance, ["Total Liabilities Net Minority Interest", "Total Liabilities"]) or info.get("totalLiabilities")
    st.metric("Total assets", compact(total_assets, currency))
    st.metric("Total debt", compact(total_debt, currency))
    st.metric("Assets / debt", ratio(total_assets / total_debt if total_assets is not None and total_debt else None))
    st.metric("Assets / liabilities", ratio(total_assets / total_liabilities if total_assets is not None and total_liabilities else None))
    st.caption("Ratios use the latest available balance-sheet figures; a dash means the provider did not report the value.")

st.divider()
st.markdown("#### Worst historical drop (maximum drawdown)")
st.caption("This answers: how far did the stock fall from a previous high before reaching its next bottom? It helps show the severity of a past downturn and is not a forecast of future losses.")
dd_peak_price = history.loc[dd_start, "Close"]
dd_trough_price = history.loc[dd_end, "Close"]
hypothetical_value = 10_000 * dd_trough_price / dd_peak_price if dd_peak_price else None
dd_summary = st.columns(3)
dd_summary[0].metric("Largest peak-to-trough fall", f"{max_decline:.1f}%")
dd_summary[1].metric("Prior peak", money(dd_peak_price, currency), dd_start.strftime("%b %d, %Y"))
dd_summary[2].metric("Later bottom", money(dd_trough_price, currency), dd_end.strftime("%b %d, %Y"))
st.info(f"Illustration: $10,000 at that prior peak would have been worth about {money(hypothetical_value, currency)} at the bottom, based on adjusted prices. This is a historical example, not a prediction.")
dd_view = ten_year_history.loc[dd_start:dd_end]
dd_fig = go.Figure(go.Scatter(x=dd_view.index, y=dd_view["Close"], mode="lines", line=dict(color="#bc775e", width=2), fill="tozeroy", fillcolor="rgba(188,119,94,.10)", hovertemplate="%{x|%b %d, %Y}<br>" + currency + " %{y:,.2f}<extra></extra>"))
dd_fig.add_trace(go.Scatter(x=[dd_start, dd_end], y=[dd_peak_price, dd_trough_price], mode="markers+text", text=["Peak", "Bottom"], textposition=["bottom right", "bottom right"], marker=dict(color=["#5c8655", "#2f6bce"], size=12, line=dict(color="#ffffff", width=2)), showlegend=False, hovertemplate="%{text}<br>%{x|%b %d, %Y}<br>" + currency + " %{y:,.2f}<extra></extra>"))
dd_fig.update_layout(height=210, margin=dict(l=5, r=5, t=8, b=5), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#778178", size=11), xaxis=dict(showgrid=False, linecolor="#e6e9e3"), yaxis=dict(title=None, gridcolor="#e9ece7", side="right"), hovermode="x unified")
dd_padding = (dd_view["Close"].max() - dd_view["Close"].min()) * 0.15 or abs(dd_peak_price) * 0.05 or 1
dd_fig.update_yaxes(range=[dd_view["Close"].min() - dd_padding, dd_view["Close"].max() + dd_padding])
st.plotly_chart(dd_fig, use_container_width=True, config={"displayModeBar": False})

st.markdown("<div style='padding:16px 18px;border:1px solid #e6e9e3;border-radius:12px;color:#788178;font-size:12px'>Data is provided by Yahoo Finance through yfinance and may be delayed, incomplete, or unavailable. This tool is for informational and educational use, not investment advice. Financial statement labels and coverage can vary by company.</div>", unsafe_allow_html=True)

st.divider()
st.markdown("#### Stock scanner")
st.caption("Scan up to 20 tickers at a time. Enter symbols separated by commas; results include price, daily change, volume, market cap, and trailing P/E.")
scan_input_col, scan_button_col = st.columns([5, 1])
with scan_input_col:
    scan_query = st.text_input("Tickers to scan", placeholder="AAPL, MSFT, GOOG", max_chars=200, label_visibility="collapsed", key="stock_scanner_query")
with scan_button_col:
    scan_clicked = st.button("Scan →", type="primary", use_container_width=True, key="stock_scanner_button")

filter_cols = st.columns(4)
with filter_cols[0]:
    change_range = st.slider("Daily change range (%)", min_value=-100, max_value=100, value=(-100, 100), step=1, key="stock_scanner_change_range")
with filter_cols[1]:
    max_pe = st.number_input("Max trailing P/E (0 = no limit)", min_value=0.0, value=0.0, step=1.0, key="stock_scanner_max_pe")
with filter_cols[2]:
    min_market_cap = st.number_input("Min market cap ($B)", min_value=0.0, value=0.0, step=1.0, key="stock_scanner_min_market_cap")
with filter_cols[3]:
    min_volume = st.number_input("Min daily volume", min_value=0, value=0, step=100000, key="stock_scanner_min_volume")

if scan_clicked:
    scan_symbols = tuple(dict.fromkeys(item.strip().upper() for item in scan_query.split(",") if item.strip()))
    if not scan_symbols:
        st.warning("Enter one or more ticker symbols to scan.")
    elif len(scan_symbols) > 20:
        st.warning("Scan up to 20 tickers at a time.")
    else:
        with st.spinner(f"Scanning {len(scan_symbols)} ticker(s)…"):
            st.session_state["stock_scanner_results"] = scan_ticker_list(scan_symbols)

if st.session_state.get("stock_scanner_results"):
    scanner_results = pd.DataFrame(st.session_state["stock_scanner_results"])
    change_min, change_max = change_range
    if change_min > -100:
        scanner_results = scanner_results[scanner_results["Day change (%)"].notna() & (scanner_results["Day change (%)"] >= change_min)]
    if change_max < 100:
        scanner_results = scanner_results[scanner_results["Day change (%)"].notna() & (scanner_results["Day change (%)"] <= change_max)]
    if max_pe > 0:
        scanner_results = scanner_results[
            scanner_results["Trailing P/E"].notna()
            & (scanner_results["Trailing P/E"] > 0)
            & (scanner_results["Trailing P/E"] <= max_pe)
        ]
    if min_market_cap > 0:
        scanner_results = scanner_results[scanner_results["Market cap ($B)"].notna() & (scanner_results["Market cap ($B)"] >= min_market_cap)]
    if min_volume > 0:
        scanner_results = scanner_results[scanner_results["Volume"].notna() & (scanner_results["Volume"] >= min_volume)]
    st.caption(f"Showing {len(scanner_results)} matching ticker(s).")
    st.dataframe(
        scanner_results,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Price": st.column_config.NumberColumn(format="$%.2f"),
            "Day change (%)": st.column_config.NumberColumn(format="%.2f%%"),
            "Volume": st.column_config.NumberColumn(format="localized"),
            "Market cap ($B)": st.column_config.NumberColumn(format="$%.1fB"),
            "Trailing P/E": st.column_config.NumberColumn(format="%.2f"),
        },
    )

live_chat_room()
