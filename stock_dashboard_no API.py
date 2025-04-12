import streamlit as st
import yfinance as yf
import requests
import math
import pandas as pd

import os

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
FMP_API_KEY = os.getenv("FMP_API_KEY")

st.set_page_config(page_title="Buffett-Style Stock Dashboard", layout="wide")
st.title("\U0001F4CA Buffett-Style Stock Dashboard")

# Input
symbols = st.text_input("Enter up to 6 stock tickers (comma-separated):", "")
tickers = [s.strip().upper() for s in symbols.split(",")][:6]

# DCF Assumptions
st.sidebar.header("DCF Assumptions")
discount_rate = st.sidebar.slider("Discount Rate", 0.01, 0.20, 0.09, 0.01)
terminal_growth_rate = st.sidebar.slider("Terminal Growth Rate (after 10Y)", 0.00, 0.05, 0.03, 0.01)
growth_cap = 0.25

def get_fmp_cagr(ticker):
    try:
        url = f"https://financialmodelingprep.com/api/v3/income-statement/{ticker}?limit=6&apikey={FMP_API_KEY}"
        r = requests.get(url)
        if r.status_code != 200 or not r.json():
            return None, "FMP fetch failed"
        income_statements = r.json()
        revenues = [entry['revenue'] for entry in income_statements if 'revenue' in entry and entry['revenue'] > 0]
        if len(revenues) < 2:
            return None, "Insufficient data from FMP"
        start, end = revenues[-1], revenues[0]
        cagr = (end / start) ** (1 / (len(revenues) - 1)) - 1
        return round(cagr, 4), None
    except Exception as e:
        return None, str(e)

def get_yf_cagr(ticker):
    try:
        t = yf.Ticker(ticker)
        financials = t.financials
        if financials is None or financials.empty or "Total Revenue" not in financials.index:
            return None, "Missing financials in yfinance"
        revenues = financials.loc["Total Revenue"].dropna().sort_index(ascending=False)
        if len(revenues) < 2:
            return None, "Too few revenue entries"
        start, end = revenues.iloc[-1], revenues.iloc[0]
        cagr = (end / start) ** (1 / (len(revenues) - 1)) - 1
        return round(cagr, 4), f"Used {len(revenues)} years from yfinance"
    except Exception as e:
        return None, str(e)

def get_fmp_data(ticker):
    try:
        url = f"https://financialmodelingprep.com/api/v3/profile/{ticker}?apikey={FMP_API_KEY}"
        r = requests.get(url)
        if r.status_code == 200 and r.json():
            return r.json()[0]
    except:
        pass
    return None

def get_fmp_key_metrics(ticker):
    try:
        metrics_url = f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/{ticker}?apikey={FMP_API_KEY}"
        r = requests.get(metrics_url)
        metrics = r.json()[0] if r.status_code == 200 and r.json() else {}
        return metrics
    except Exception as e:
        print(f"Error fetching metrics for {ticker}: {e}")
        return None

def get_yf_data(ticker):
    try:
        t = yf.Ticker(ticker)
        info = t.info
        growth = info.get("earningsQuarterlyGrowth")
        return info, growth
    except:
        return None, None

def infer_curated_moat(name, market_cap, description=""):
    moat = "Narrow"
    durability = "Low"
    if market_cap > 1e12:
        moat = "Wide"
        durability = "High"
    elif market_cap > 1e10:
        moat = "Moderate"
        durability = "Medium"
    keywords = ["ecosystem", "dominant", "monopoly", "sticky", "recurring", "network effect"]
    if any(keyword in description.lower() for keyword in keywords):
        moat = "Wide"
    return moat, durability

def get_stock_data(ticker):
    try:
        fmp_profile = get_fmp_data(ticker)
        fmp_metrics = get_fmp_key_metrics(ticker)
        yf_data, est_growth = get_yf_data(ticker)

        name = fmp_profile.get("companyName") if fmp_profile else yf_data.get("longName", ticker)
        price = float(fmp_profile["price"]) if fmp_profile and "price" in fmp_profile else yf_data.get("currentPrice", 0)
        pe = fmp_metrics.get("peRatioTTM") if fmp_metrics and "peRatioTTM" in fmp_metrics else yf_data.get("trailingPE")
        market_cap = float(fmp_profile.get("mktCap")) if fmp_profile and "mktCap" in fmp_profile else yf_data.get("marketCap")
        shares_outstanding = float(fmp_profile.get("sharesOutstanding")) if fmp_profile and "sharesOutstanding" in fmp_profile else yf_data.get("sharesOutstanding")

        fcf = None
        if fmp_metrics and "freeCashFlowTTM" in fmp_metrics:
            fcf = float(fmp_metrics["freeCashFlowTTM"])
        if not fcf and yf_data and "freeCashflow" in yf_data:
            fcf = yf_data["freeCashflow"]

        # Get growth rate from FMP, fallback to yfinance, then fallback to 8%
        cagr, source_note = get_fmp_cagr(ticker)
        if cagr is None:
            cagr, source_note = get_yf_cagr(ticker)
        if cagr is None:
            cagr = 0.08
            source_note = "Used fallback growth rate of 8%"

        if source_note:
            st.warning(f"[{ticker}] {source_note}")

        if fcf and shares_outstanding:
            growth_rate_high = min(cagr, growth_cap)
            growth_rate_stable = 0.06

            intrinsic_value = 0
            current_fcf = fcf

            for year in range(1, 6):
                discounted = current_fcf / (1 + discount_rate) ** year
                intrinsic_value += discounted
                current_fcf *= (1 + growth_rate_high)

            for year in range(6, 11):
                discounted = current_fcf / (1 + discount_rate) ** year
                intrinsic_value += discounted
                current_fcf *= (1 + growth_rate_stable)

            terminal_value = current_fcf * (1 + terminal_growth_rate) / (discount_rate - terminal_growth_rate)
            discounted_terminal = terminal_value / (1 + discount_rate) ** 10
            intrinsic_value += discounted_terminal

            intrinsic_value_per_share = intrinsic_value / shares_outstanding
            margin_of_safety = (intrinsic_value_per_share - price) / price * 100
            growth_rate_high_display = f"{growth_rate_high*100:.2f}%"
        else:
            intrinsic_value_per_share = "N/A"
            margin_of_safety = "N/A"
            growth_rate_high = None
            growth_rate_high_display = "N/A"

        score = 0
        if isinstance(pe, (int, float)) and pe < 20:
            score += 1
        if isinstance(margin_of_safety, (int, float)) and margin_of_safety > 25:
            score += 1
        if fcf and fcf > 0:
            score += 1

        description = fmp_profile.get("description", "") if fmp_profile else ""
        curated_moat, durability = infer_curated_moat(name, market_cap, description)

        return {
            "Ticker": ticker,
            "Name": name,
            "Price": f"${price:.2f}",
            "PE Ratio": round(pe) if isinstance(pe, (int, float)) else "N/A",
            "Market Cap": f"${market_cap / 1e12:.2f}T" if market_cap > 1e12 else f"${market_cap / 1e9:.2f}B",
            "FCF (Annual)": f"${fcf / 1e9:.2f}B" if fcf else "N/A",
            "Growth Rate (5Y)": growth_rate_high_display,
            "DCF Value": f"${intrinsic_value_per_share:.2f}" if isinstance(intrinsic_value_per_share, (int, float)) else "N/A",
            "Margin of Safety": f"{round(margin_of_safety, 2)}%" if isinstance(margin_of_safety, (int, float)) else "N/A",
            "Score ⭐": f"{'🌟' * score} ({score}/3)",
            "FCF Growth Quality": "🟢 Strong" if growth_rate_high and growth_rate_high > 0.15 else "🟡 Moderate" if growth_rate_high and growth_rate_high > 0.08 else "🔵 Steady" if growth_rate_high and growth_rate_high > 0.04 else "🔴 Weak",
            "Moat Strength": f"{'🟢' if score == 3 else '🟡' if score == 2 else '🔴'} {('Wide' if score == 3 else 'Moderate' if score == 2 else 'Narrow' if score == 1 else 'None')}",
            "Curated Moat": f"{'🟢' if curated_moat == 'Wide' else '🟡' if curated_moat == 'Moderate' else '🔴'} {curated_moat}",
            "Durability": f"{'🔒' if durability == 'High' else '🟡'} {durability}",
            "Overall Rating": "\U0001F7E2 Strong Buy" if margin_of_safety != "N/A" and margin_of_safety > 40 else \
                              "✅ Consider Buy" if margin_of_safety > 25 else \
                              "\U0001F7E1 Watchlist" if margin_of_safety > 10 else \
                              "\U0001F535 Safe but Not a Deal" if margin_of_safety > 0 else \
                              "❌ Do Not Buy",
            "SortValue": score + (margin_of_safety if isinstance(margin_of_safety, (int, float)) else 0) / 100
        }
    except Exception as e:
        return {"Ticker": ticker, "Error": str(e)}

# Display data
data = [get_stock_data(t) for t in tickers if t]
df = pd.DataFrame(data)
if not df.empty:
    df.sort_values("SortValue", ascending=False, inplace=True)
    df.drop(columns=["SortValue"], inplace=True)

    st.markdown("""
        ###  How to Interpret This Dashboard

        This dashboard is inspired by **Buffett-style** value investing principles. It evaluates companies based on **three core criteria**:

        - **Price-to-Earnings Ratio (P/E < 20):** Indicates whether the stock is reasonably priced relative to its earnings.
        - **Margin of Safety (>25%):** Based on Discounted Cash Flow (DCF) valuation. A higher margin indicates potential undervaluation.
        - **Free Cash Flow (FCF > 0):** Positive FCF shows a company’s ability to generate real cash profits.

        ###  Growth and Quality Indicators

        - **FCF Growth Quality** shows the consistency and strength of Free Cash Flow growth.
        - **Moat Strength** reflects a company's competitive edge, inferred from its fundamentals.
        - **Curated Moat & Durability** are estimated based on market cap and business model resilience.

        ###  Valuation Approach

        We use a **2-stage Discounted Cash Flow (DCF) model)**:

        - **Stage 1 (Years 1–5):** Applies a high growth rate (based on analyst estimates or calculated CAGR, capped at 25%)
        - **Stage 2 (Years 6–10):** Applies a stable growth rate (default: 6%)
        - The **Terminal Value** accounts for long-term future cash flows after 10 years.

        ###  Investment Use

        - **Strong Buy**: Stock appears deeply undervalued with strong fundamentals.
        - **Consider Buy**: Reasonable value with growth potential.
        - **Watchlist**: Could be worth buying at a lower price or when fundamentals improve.
        - **Do Not Buy**: Stock may be overpriced or has weak fundamentals.

        ⚠️ *This dashboard is a research tool, not financial advice. Always perform your own due diligence before investing.*
    """, unsafe_allow_html=True)

    st.markdown("""
        <h3 style='display: flex; align-items: center;'>\U0001F4C1 Comparison Table</h3>
    """, unsafe_allow_html=True)

    st.dataframe(
        df.style
        .set_properties(subset=["Score ⭐"], **{"background-color": "#e0f7fa"})
        .set_properties(subset=["FCF Growth Quality"], **{"background-color": "#f1f8e9"})
        .set_properties(subset=["Moat Strength"], **{"background-color": "#f3e5f5"})
        .set_properties(subset=["Curated Moat"], **{"background-color": "#f3e5f5"})
        .set_properties(subset=["Durability"], **{"background-color": "#fff3e0"})
    )
else:
    st.warning("Please enter valid tickers to display data.")
