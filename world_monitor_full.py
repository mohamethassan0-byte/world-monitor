"""
🌍 WORLD MONITOR — professional global dashboard (single file, Streamlit).

Run locally :  python -m streamlit run world_monitor.py
Deploy      :  push this file + requirements.txt to GitHub -> share.streamlit.io

Only free sources, no API keys required:
 REST Countries · World Bank · disease.sh (COVID) · WHO Disease Outbreak News · CDC travel notices
 Google News RSS · BBC/NPR/Guardian/Al Jazeera/DW/France24/Sky/CBS/ABC-AU RSS · USGS · NASA EONET · GDACS
 Open-Meteo (weather, air quality, geocoding) · Wikidata (cities) · Yahoo Finance · CoinGecko
 open.er-api.com (FX) · wheretheiss.at · Open Notify · NASA APOD/NeoWs · NOAA SWPC · Launch Library 2
 Wikimedia · Hacker News · Google Trends RSS · YouTube live streams · NOAA GOES / NASA SDO imagery
Optional: add WINDY_KEY to Streamlit secrets to show real webcam snapshots near any city.
"""
import calendar
import html
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

st.set_page_config(page_title="World Monitor", page_icon="🌍", layout="wide", initial_sidebar_state="expanded")

HEADERS = {"User-Agent": "WorldMonitorDashboard/2.0 (Streamlit app; educational use)"}
ERRORS: list = []
_PLOT_N = [0]

st.markdown(
    """
<style>
.block-container{padding-top:1.1rem;max-width:1500px}
.hero{background:linear-gradient(120deg,#0f2f6b 0%,#1d4ed8 55%,#0891b2 100%);color:#fff;padding:20px 26px;border-radius:16px;margin-bottom:14px}
.hero h1{margin:0;font-size:1.8rem;color:#fff;padding:0}
.hero p{margin:4px 0 0 0;opacity:.88;font-size:.92rem}
.kpi{border:1px solid rgba(128,128,128,.25);background:rgba(128,128,128,.07);border-radius:14px;padding:11px 15px;margin-bottom:8px}
.kpi .kl{font-size:.72rem;opacity:.7;text-transform:uppercase;letter-spacing:.05em}
.kpi .kv{font-size:1.5rem;font-weight:700;line-height:1.25}
.kpi .ks{font-size:.78rem;opacity:.75}
.kpi .up{color:#16a34a;opacity:1}.kpi .down{color:#dc2626;opacity:1}
.clock{text-align:center;border:1px solid rgba(128,128,128,.25);border-radius:12px;padding:6px 2px;background:rgba(128,128,128,.06)}
.clock span{display:block;font-size:.7rem;opacity:.7}.clock b{font-size:1.1rem}.clock i{display:block;font-size:.64rem;opacity:.6;font-style:normal}
.src-tag{font-size:.74rem;opacity:.65}
.chip{display:inline-block;padding:1px 9px;border-radius:99px;font-size:.7rem;font-weight:600;color:#fff;margin-right:6px}
</style>
""",
    unsafe_allow_html=True,
)

# =============================================================================
# CONSTANTS
# =============================================================================
REGIONS = {
    "World": None,
    "Africa": dict(lon=[-26, 62], lat=[-38, 40]),
    "Asia": dict(lon=[24, 180], lat=[-12, 82]),
    "Europe": dict(lon=[-25, 50], lat=[33, 72]),
    "North America": dict(lon=[-170, -50], lat=[5, 75]),
    "South America": dict(lon=[-85, -30], lat=[-57, 14]),
    "Oceania": dict(lon=[108, 180], lat=[-50, 2]),
}

WB_IND = {
    "gdp": ("NY.GDP.MKTP.CD", "GDP (US$)"),
    "gdp_pc": ("NY.GDP.PCAP.CD", "GDP per capita (US$)"),
    "gdp_growth": ("NY.GDP.MKTP.KD.ZG", "GDP growth (%)"),
    "life_exp": ("SP.DYN.LE00.IN", "Life expectancy (years)"),
    "inflation": ("FP.CPI.TOTL.ZG", "Inflation (%)"),
    "unemployment": ("SL.UEM.TOTL.ZS", "Unemployment (%)"),
    "internet": ("IT.NET.USER.ZS", "Internet users (% of pop.)"),
    "mobile": ("IT.CEL.SETS.P2", "Mobile subscriptions (per 100)"),
    "broadband": ("IT.NET.BBND.P2", "Fixed broadband (per 100)"),
    "co2_pc": ("EN.ATM.CO2E.PC", "CO₂ per capita (tonnes)"),
    "urban": ("SP.URB.TOTL.IN.ZS", "Urban population (%)"),
    "infant_mort": ("SP.DYN.IMRT.IN", "Infant mortality (per 1,000)"),
    "electricity": ("EG.ELC.ACCS.ZS", "Access to electricity (%)"),
    "health_exp": ("SH.XPD.CHEX.GD.ZS", "Health spending (% of GDP)"),
}
HIGHER_BETTER = {"gdp_pc": 1, "gdp_growth": 1, "life_exp": 1, "internet": 1, "mobile": 1, "broadband": 1,
                 "electricity": 1, "urban": 1, "health_exp": 1, "inflation": 0, "unemployment": 0,
                 "infant_mort": 0, "co2_pc": 0}

MAP_METRICS = {
    "Population": ("population", "Viridis"), "Land area (km²)": ("area", "Cividis"),
    "Population density (per km²)": ("density", "Plasma"), "GDP (US$)": ("gdp", "Viridis"),
    "GDP per capita (US$)": ("gdp_pc", "Viridis"), "GDP growth (%)": ("gdp_growth", "RdYlGn"),
    "Life expectancy (years)": ("life_exp", "RdYlGn"), "Inflation (%)": ("inflation", "YlOrRd"),
    "Unemployment (%)": ("unemployment", "YlOrRd"), "Internet users (% of pop.)": ("internet", "Blues"),
    "Mobile subscriptions (per 100)": ("mobile", "Blues"), "Fixed broadband (per 100)": ("broadband", "Blues"),
    "CO₂ per capita (t)": ("co2_pc", "OrRd"), "Urban population (%)": ("urban", "Purples"),
    "Infant mortality (per 1,000)": ("infant_mort", "YlOrRd"), "Electricity access (%)": ("electricity", "YlGn"),
    "Health spending (% GDP)": ("health_exp", "Teal"), "COVID-19 cases per million": ("cases_pm", "Reds"),
    "COVID-19 deaths per million": ("deaths_pm", "Reds"),
}

MARKETS = {
    "Americas": {"S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "TSX (Canada)": "^GSPTSE", "Bovespa (Brazil)": "^BVSP"},
    "Europe": {"FTSE 100": "^FTSE", "DAX": "^GDAXI", "CAC 40": "^FCHI", "Euro Stoxx 50": "^STOXX50E"},
    "Asia-Pacific": {"Nikkei 225": "^N225", "Hang Seng": "^HSI", "Shanghai Comp.": "000001.SS", "KOSPI": "^KS11",
                     "Nifty 50": "^NSEI", "KLCI": "^KLSE", "Straits Times": "^STI", "ASX 200": "^AXJO"},
    "Commodities": {"Gold": "GC=F", "Silver": "SI=F", "Crude Oil WTI": "CL=F", "Brent Crude": "BZ=F",
                    "Natural Gas": "NG=F", "Copper": "HG=F"},
    "Rates & Risk": {"US 10Y Yield": "^TNX", "VIX (fear index)": "^VIX", "US Dollar Index": "DX-Y.NYB"},
}

NEWS_FEEDS = {
    "World": {
        "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
        "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
        "NPR": "https://feeds.npr.org/1004/rss.xml",
        "The Guardian": "https://www.theguardian.com/world/rss",
        "DW": "https://rss.dw.com/rdf/rss-en-all",
        "France 24": "https://www.france24.com/en/rss",
        "Sky News": "https://feeds.skynews.com/feeds/rss/world.xml",
        "CBS News": "https://www.cbsnews.com/latest/rss/world",
        "ABC Australia": "https://www.abc.net.au/news/feed/2942460/rss.xml",
    },
    "Business": {
        "BBC": "http://feeds.bbci.co.uk/news/business/rss.xml", "NPR": "https://feeds.npr.org/1006/rss.xml",
        "The Guardian": "https://www.theguardian.com/business/rss", "Sky News": "https://feeds.skynews.com/feeds/rss/business.xml",
    },
    "Technology": {
        "BBC": "http://feeds.bbci.co.uk/news/technology/rss.xml", "NPR": "https://feeds.npr.org/1019/rss.xml",
        "The Guardian": "https://www.theguardian.com/technology/rss", "Sky News": "https://feeds.skynews.com/feeds/rss/technology.xml",
    },
    "Science & Environment": {
        "BBC": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml", "NPR": "https://feeds.npr.org/1007/rss.xml",
        "The Guardian": "https://www.theguardian.com/science/rss",
    },
    "Health": {"BBC": "http://feeds.bbci.co.uk/news/health/rss.xml", "NPR": "https://feeds.npr.org/1128/rss.xml"},
}

EDITIONS = {
    "🇺🇸 United States": ("en-US", "US", "US:en"), "🇬🇧 United Kingdom": ("en-GB", "GB", "GB:en"),
    "🇮🇳 India": ("en-IN", "IN", "IN:en"), "🇲🇾 Malaysia": ("en-MY", "MY", "MY:en"),
    "🇸🇬 Singapore": ("en-SG", "SG", "SG:en"), "🇦🇺 Australia": ("en-AU", "AU", "AU:en"),
    "🇨🇦 Canada": ("en-CA", "CA", "CA:en"), "🇿🇦 South Africa": ("en-ZA", "ZA", "ZA:en"),
    "🇳🇬 Nigeria": ("en-NG", "NG", "NG:en"), "🇵🇭 Philippines": ("en-PH", "PH", "PH:en"),
    "🇮🇪 Ireland": ("en-IE", "IE", "IE:en"), "🇳🇿 New Zealand": ("en-NZ", "NZ", "NZ:en"),
}
WHEN = {"Past hour": "1h", "Past 24 hours": "1d", "Past week": "7d", "Past month": "30d", "Past year": "1y"}

DISEASES = ["Plague", "Cholera", "Ebola", "Marburg", "Mpox", "Measles", "Dengue", "Malaria", "Avian influenza H5N1",
            "Polio", "Anthrax", "Nipah", "MERS", "Chikungunya", "Yellow fever", "Tuberculosis", "Lassa fever",
            "Meningitis", "Diphtheria", "Typhoid", "Rabies", "Zika", "COVID-19", "Influenza", "Custom…"]

CITIES = [
    ("New York", "United States", "North America", 40.71, -74.01), ("Los Angeles", "United States", "North America", 34.05, -118.24),
    ("Chicago", "United States", "North America", 41.88, -87.63), ("Toronto", "Canada", "North America", 43.65, -79.38),
    ("Mexico City", "Mexico", "North America", 19.43, -99.13), ("Havana", "Cuba", "North America", 23.11, -82.37),
    ("Panama City", "Panama", "North America", 8.98, -79.52), ("Anchorage", "United States", "North America", 61.22, -149.90),
    ("São Paulo", "Brazil", "South America", -23.55, -46.63), ("Buenos Aires", "Argentina", "South America", -34.60, -58.38),
    ("Lima", "Peru", "South America", -12.05, -77.04), ("Bogotá", "Colombia", "South America", 4.71, -74.07),
    ("Santiago", "Chile", "South America", -33.45, -70.67), ("Caracas", "Venezuela", "South America", 10.48, -66.90),
    ("London", "United Kingdom", "Europe", 51.51, -0.13), ("Paris", "France", "Europe", 48.86, 2.35),
    ("Berlin", "Germany", "Europe", 52.52, 13.40), ("Madrid", "Spain", "Europe", 40.42, -3.70),
    ("Rome", "Italy", "Europe", 41.90, 12.50), ("Moscow", "Russia", "Europe", 55.76, 37.62),
    ("Istanbul", "Türkiye", "Europe", 41.01, 28.98), ("Stockholm", "Sweden", "Europe", 59.33, 18.07),
    ("Athens", "Greece", "Europe", 37.98, 23.73), ("Kyiv", "Ukraine", "Europe", 50.45, 30.52),
    ("Reykjavik", "Iceland", "Europe", 64.15, -21.94), ("Cairo", "Egypt", "Africa", 30.04, 31.24),
    ("Lagos", "Nigeria", "Africa", 6.52, 3.38), ("Nairobi", "Kenya", "Africa", -1.29, 36.82),
    ("Johannesburg", "South Africa", "Africa", -26.20, 28.05), ("Casablanca", "Morocco", "Africa", 33.57, -7.59),
    ("Addis Ababa", "Ethiopia", "Africa", 9.03, 38.74), ("Accra", "Ghana", "Africa", 5.60, -0.19),
    ("Kinshasa", "DR Congo", "Africa", -4.44, 15.27), ("Dubai", "UAE", "Asia", 25.20, 55.27),
    ("Riyadh", "Saudi Arabia", "Asia", 24.71, 46.68), ("Tehran", "Iran", "Asia", 35.69, 51.39),
    ("Karachi", "Pakistan", "Asia", 24.86, 67.01), ("Delhi", "India", "Asia", 28.61, 77.21),
    ("Mumbai", "India", "Asia", 19.08, 72.88), ("Dhaka", "Bangladesh", "Asia", 23.81, 90.41),
    ("Bangkok", "Thailand", "Asia", 13.76, 100.50), ("Kuala Lumpur", "Malaysia", "Asia", 3.14, 101.69),
    ("Singapore", "Singapore", "Asia", 1.35, 103.82), ("Jakarta", "Indonesia", "Asia", -6.21, 106.85),
    ("Manila", "Philippines", "Asia", 14.60, 120.98), ("Beijing", "China", "Asia", 39.90, 116.41),
    ("Shanghai", "China", "Asia", 31.23, 121.47), ("Seoul", "South Korea", "Asia", 37.57, 126.98),
    ("Tokyo", "Japan", "Asia", 35.68, 139.69), ("Tashkent", "Uzbekistan", "Asia", 41.30, 69.24),
    ("Sydney", "Australia", "Oceania", -33.87, 151.21), ("Perth", "Australia", "Oceania", -31.95, 115.86),
    ("Auckland", "New Zealand", "Oceania", -36.85, 174.76), ("Port Moresby", "Papua New Guinea", "Oceania", -9.44, 147.18),
    ("Suva", "Fiji", "Oceania", -18.14, 178.44),
]

LIVE_CHANNELS = {
    "Al Jazeera English": "UCNye-wNBqNL5ZzHSJj3l8Bg", "Sky News": "UCoMdktPbSTixAyNGwb-UYkQ",
    "DW News": "UCknLrEdhRCp1aegoMqRaCZg", "France 24 English": "UCQfwfsi5VrQ8yKZ-UWmAEFg",
    "Euronews English": "UCSrZ3UV4jOidv8ppoVuvW9Q", "NASA": "UCLA_DiR1FfKNvjuUpBHmylQ",
    "Bloomberg TV": "UCIALMKvObZNtJ6AmdCLP7Lg", "ABC News (US)": "UCBi2mrWuNuyYy4gbM6fU18Q",
    "CNA (Singapore)": "UC83jt4dlz1Gjl58fzQrrIqg", "TRT World": "UC7fWeaHhqgM4Ry-RMpM2YYw",
    "WION (India)": "UC_gUM8rL-Lrg6O3adPW9K1g",
}
IMAGERY = {
    "GOES-East (Americas) — full disk": "https://cdn.star.nesdis.noaa.gov/GOES19/ABI/FD/GEOCOLOR/678x678.jpg",
    "GOES-West (Pacific) — full disk": "https://cdn.star.nesdis.noaa.gov/GOES18/ABI/FD/GEOCOLOR/678x678.jpg",
    "Sun — SDO 193Å (corona)": "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_0193.jpg",
    "Sun — SDO HMI (sunspots)": "https://sdo.gsfc.nasa.gov/assets/img/latest/latest_512_HMIIC.jpg",
}


# =============================================================================
# HELPERS
# =============================================================================
def get_json(url, params=None, timeout=20, headers=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)
    r = requests.get(url, params=params, headers=h, timeout=timeout)
    r.raise_for_status()
    return r.json()


def strip_html(t):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t or "")).strip()


def esc(t):
    return str(t).replace("$", "\\$").replace("[", "\\[").replace("]", "\\]")


def fnum(x, d=1):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    if np.isnan(x) or np.isinf(x):
        return "—"
    for u, v in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("K", 1e4)):
        if abs(x) >= v:
            return f"{x / v:,.{d}f}{u}"
    return f"{x:,.{d}f}"


def kpi(col, label, value, sub="", tone=""):
    col.markdown(
        f"<div class='kpi'><div class='kl'>{label}</div><div class='kv'>{value}</div>"
        f"<div class='ks {tone}'>{sub}&nbsp;</div></div>", unsafe_allow_html=True)


def hero(title, sub):
    st.markdown(f"<div class='hero'><h1>{title}</h1><p>{sub}</p></div>", unsafe_allow_html=True)


def plot(fig):
    _PLOT_N[0] += 1
    st.plotly_chart(fig, key=f"plt{_PLOT_N[0]}")


def img(url, caption=None):
    try:
        st.image(url, caption=caption, width="stretch")
    except Exception:  # noqa: BLE001
        st.image(url, caption=caption, use_container_width=True)


def embed(url, height=420):
    try:
        components.iframe(url, height=height)
    except Exception:  # noqa: BLE001
        components.html(f'<iframe src="{url}" width="100%" height="{height}" frameborder="0" allowfullscreen></iframe>', height=height + 6)


def get_secret(name):
    try:
        return st.secrets.get(name)
    except Exception:  # noqa: BLE001
        return None


def in_region(df, region, lat="lat", lon="lon"):
    r = REGIONS.get(region)
    if not r or df is None or df.empty:
        return df
    return df[df[lat].between(*r["lat"]) & df[lon].between(*r["lon"])]


def style_geo(fig, region="World", height=520, detail=False):
    r = REGIONS.get(region)
    geo = dict(
        projection_type="natural earth", showland=True, landcolor="rgba(140,150,165,0.22)",
        showocean=True, oceancolor="rgba(70,130,200,0.10)", showlakes=False, showcountries=True,
        countrycolor="rgba(140,150,165,0.55)", showcoastlines=True, coastlinecolor="rgba(140,150,165,0.75)",
        showframe=False, bgcolor="rgba(0,0,0,0)", resolution=50 if (r or detail) else 110,
    )
    if r:
        geo.update(lonaxis_range=r["lon"], lataxis_range=r["lat"])
    fig.update_geos(**geo)
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.02, x=0))
    return fig


def clean_layout(fig, height=340):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=30, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.15))
    return fig


def weather_label(code):
    code = int(code)
    if code == 0: return "☀️ Clear"
    if code in (1, 2): return "🌤️ Mostly clear"
    if code == 3: return "☁️ Overcast"
    if code in (45, 48): return "🌫️ Fog"
    if 51 <= code <= 57: return "🌦️ Drizzle"
    if 61 <= code <= 67: return "🌧️ Rain"
    if 71 <= code <= 77: return "❄️ Snow"
    if 80 <= code <= 82: return "🌧️ Showers"
    if code in (85, 86): return "🌨️ Snow showers"
    if code >= 95: return "⛈️ Thunderstorm"
    return "—"


def aqi_label(v):
    if v is None or (isinstance(v, float) and np.isnan(v)): return "—"
    return ("Good" if v <= 50 else "Moderate" if v <= 100 else "Unhealthy (sensitive)" if v <= 150
            else "Unhealthy" if v <= 200 else "Very unhealthy" if v <= 300 else "Hazardous")


# =============================================================================
# DATA LOADERS
# =============================================================================
@st.cache_data(ttl=86400, show_spinner=False)
def load_country_detail(iso3):
    return get_json(f"https://restcountries.com/v3.1/alpha/{iso3}")[0]


def _wb_latest(code):
    d = get_json(f"https://api.worldbank.org/v2/country/all/indicator/{code}",
                 {"format": "json", "per_page": 20000, "mrnev": 1}, timeout=40)
    rows = d[1] if isinstance(d, list) and len(d) > 1 and d[1] else []
    return {r["countryiso3code"]: r["value"] for r in rows if r.get("countryiso3code") and r.get("value") is not None}


@st.cache_data(ttl=43200, show_spinner=False)
def load_wb_snapshot():
    def one(k):
        try:
            return k, _wb_latest(WB_IND[k][0])
        except Exception:  # noqa: BLE001
            return k, {}
    with ThreadPoolExecutor(6) as ex:
        res = dict(ex.map(one, list(WB_IND)))
    df = pd.DataFrame(res)
    if df.empty:
        raise RuntimeError("World Bank returned no data")
    df.index.name = "iso3"
    return df.reset_index()


@st.cache_data(ttl=43200, show_spinner=False)
def load_wb_multi(iso3s, code, start=1990):
    d = get_json(f"https://api.worldbank.org/v2/country/{';'.join(iso3s)}/indicator/{code}",
                 {"format": "json", "per_page": 3000, "date": f"{start}:{datetime.now().year}"}, timeout=30)
    rows = d[1] if isinstance(d, list) and len(d) > 1 and d[1] else []
    out = [dict(iso3=r["countryiso3code"], country=r["country"]["value"], year=int(r["date"]), value=r["value"])
           for r in rows if r.get("value") is not None]
    if not out:
        return pd.DataFrame(columns=["iso3", "country", "year", "value"])
    return pd.DataFrame(out).sort_values(["country", "year"]).reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def load_covid_countries():
    rows = []
    for c in get_json("https://disease.sh/v3/covid-19/countries"):
        iso = (c.get("countryInfo") or {}).get("iso3")
        if not iso:
            continue
        rows.append(dict(iso3=iso, cases=c.get("cases"), today_cases=c.get("todayCases"), deaths=c.get("deaths"),
                         today_deaths=c.get("todayDeaths"), active=c.get("active"), cases_pm=c.get("casesPerOneMillion"),
                         deaths_pm=c.get("deathsPerOneMillion")))
    return pd.DataFrame(rows).drop_duplicates("iso3")


@st.cache_data(ttl=1800, show_spinner=False)
def load_covid_global():
    return get_json("https://disease.sh/v3/covid-19/all")


@st.cache_data(ttl=3600, show_spinner=False)
def load_covid_history(code="all"):
    d = get_json(f"https://disease.sh/v3/covid-19/historical/{code}", {"lastdays": "all"})
    tl = d if code == "all" else d.get("timeline", d)
    df = pd.DataFrame({"cases": pd.Series(tl["cases"]), "deaths": pd.Series(tl["deaths"])})
    df.index = pd.to_datetime(df.index, format="%m/%d/%y")
    df.index.name = "date"
    df["new_cases"] = df["cases"].diff().clip(lower=0)
    df["new_deaths"] = df["deaths"].diff().clip(lower=0)
    df["new_cases_7d"] = df["new_cases"].rolling(7).mean()
    df["new_deaths_7d"] = df["new_deaths"].rolling(7).mean()
    return df.reset_index()


def world_table():
    c = safe(load_countries, pd.DataFrame())
    if c.empty:
        return c
    df = c
    wb = safe(load_wb_snapshot, pd.DataFrame())
    if not wb.empty:
        df = df.merge(wb, on="iso3", how="left")
    cv = safe(load_covid_countries, pd.DataFrame())
    if not cv.empty:
        df = df.merge(cv, on="iso3", how="left")
    for col in list(WB_IND) + ["cases", "deaths", "active", "cases_pm", "deaths_pm", "today_cases", "today_deaths"]:
        if col not in df:
            df[col] = np.nan
    return df


# ---- news -------------------------------------------------------------------
def _entries(parsed, source, limit, summaries=True):
    rows = []
    for e in parsed.entries[:limit]:
        ts = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc) if ts else None
        src = source or (e.get("source") or {}).get("title") or ""
        title = strip_html(e.get("title", ""))
        if src and title.endswith(f" - {src}"):
            title = title[: -len(src) - 3]
        rows.append(dict(source=src, title=title, link=e.get("link", ""),
                         summary=strip_html(e.get("summary", ""))[:300] if summaries else "", published=dt))
    return pd.DataFrame(rows, columns=["source", "title", "link", "summary", "published"])


@st.cache_data(ttl=600, show_spinner=False)
def load_news(category, sources):
    feeds = {s: u for s, u in NEWS_FEEDS[category].items() if s in sources}

    def one(kv):
        try:
            r = requests.get(kv[1], headers=HEADERS, timeout=12)
            r.raise_for_status()
            return _entries(feedparser.parse(r.content), kv[0], 25)
        except Exception:  # noqa: BLE001
            return pd.DataFrame()
    with ThreadPoolExecutor(8) as ex:
        parts = [p for p in ex.map(one, feeds.items()) if not p.empty]
    if not parts:
        raise RuntimeError("no news feeds reachable")
    df = pd.concat(parts).drop_duplicates("title")
    return df.sort_values("published", ascending=False, na_position="last").reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def load_gnews(query, edition=("en-US", "US", "US:en"), when="7d", limit=40):
    hl, gl, ceid = edition
    q = f"{query} when:{when}" if when else query
    r = requests.get(f"https://news.google.com/rss/search?q={quote_plus(q)}&hl={hl}&gl={gl}&ceid={ceid}", headers=HEADERS, timeout=20)
    r.raise_for_status()
    df = _entries(feedparser.parse(r.content), None, limit, summaries=False)
    return df.sort_values("published", ascending=False, na_position="last").reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def load_gnews_top(iso2, limit=30):
    r = requests.get(f"https://news.google.com/rss?hl=en&gl={iso2}&ceid={iso2}:en", headers=HEADERS, timeout=20)
    r.raise_for_status()
    return _entries(feedparser.parse(r.content), None, limit, summaries=False)


@st.cache_data(ttl=3600, show_spinner=False)
def load_rss(url, source, limit=40):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return _entries(feedparser.parse(r.content), source, limit)


@st.cache_data(ttl=3600, show_spinner=False)
def load_who_don():
    try:
        return load_rss("https://www.who.int/feeds/entity/csr/don/en/rss.xml", "WHO", 40)
    except Exception:  # noqa: BLE001
        return load_gnews('"Disease Outbreak News" WHO', when="1y", limit=30)


def parse_outbreaks(df, countries):
    """Match WHO 'Disease – Country' titles to countries so they can be mapped."""
    if df is None or df.empty or countries is None or countries.empty:
        return pd.DataFrame()
    norm = lambda s: " " + re.sub(r"[^a-z0-9 ]", " ", str(s).lower()) + " "  # noqa: E731
    names = []
    for r in countries.itertuples():
        for nm in {r.country, r.official}:
            if nm:
                names.append((norm(nm), r.iso3, r.country, r.lat, r.lon))
    names.sort(key=lambda x: -len(x[0]))
    rows = []
    for e in df.itertuples():
        parts = re.split(r"\s[-–—]\s", e.title)
        if len(parts) < 2:
            continue
        loc = norm(parts[-1])
        hit = next((n for n in names if n[0] in loc), None)
        if hit:
            rows.append(dict(disease=parts[0].strip(), country=hit[2], iso3=hit[1], lat=hit[3], lon=hit[4],
                             published=e.published, title=e.title, link=e.link))
    return pd.DataFrame(rows)


# ---- hazards ----------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def load_quakes(feed="2.5_day"):
    data = get_json(f"https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson")
    rows = []
    for f in data["features"]:
        p = f["properties"]
        lon, lat, depth = f["geometry"]["coordinates"][:3]
        if p.get("mag") is None:
            continue
        rows.append(dict(time=pd.to_datetime(p["time"], unit="ms", utc=True), magnitude=p["mag"], place=p["place"],
                         depth_km=depth, lat=lat, lon=lon, tsunami=bool(p.get("tsunami")), url=p.get("url")))
    df = pd.DataFrame(rows, columns=["time", "magnitude", "place", "depth_km", "lat", "lon", "tsunami", "url"])
    return df.sort_values("time", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=900, show_spinner=False)
def load_eonet():
    data = get_json("https://eonet.gsfc.nasa.gov/api/v3/events", {"status": "open", "limit": 150})
    rows = []
    for ev in data.get("events", []):
        geoms = ev.get("geometry") or []
        if not geoms:
            continue
        g = geoms[-1]
        co = g.get("coordinates")
        if g.get("type") != "Point" or not co or len(co) < 2:
            continue
        rows.append(dict(event=ev["title"], category=(ev.get("categories") or [{"title": "Other"}])[0]["title"],
                         date=(g.get("date") or "")[:10], lon=co[0], lat=co[1], link=ev.get("link")))
    return pd.DataFrame(rows, columns=["event", "category", "date", "lon", "lat", "link"])


@st.cache_data(ttl=900, show_spinner=False)
def load_gdacs():
    r = requests.get("https://www.gdacs.org/xml/rss.xml", headers=HEADERS, timeout=20)
    r.raise_for_status()
    types = {"EQ": "Earthquake", "TC": "Tropical cyclone", "FL": "Flood", "VO": "Volcano", "DR": "Drought", "WF": "Wildfire", "TS": "Tsunami"}
    rows = []
    for e in feedparser.parse(r.content).entries:
        lat = lon = None
        try:
            lat, lon = [float(x) for x in (e.get("georss_point") or "").split()]
        except Exception:  # noqa: BLE001
            pass
        ts = e.get("published_parsed")
        rows.append(dict(title=strip_html(e.get("title", "")), type=types.get(e.get("gdacs_eventtype"), e.get("gdacs_eventtype") or "Event"),
                         alert=str(e.get("gdacs_alertlevel") or "Green").title(), country=e.get("gdacs_country", ""),
                         published=datetime.fromtimestamp(calendar.timegm(ts), tz=timezone.utc) if ts else None,
                         link=e.get("link", ""), lat=lat, lon=lon))
    return pd.DataFrame(rows, columns=["title", "type", "alert", "country", "published", "link", "lat", "lon"])


# ---- weather ----------------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def load_multi_weather(lats, lons):
    d = get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)), "timezone": "auto",
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,pressure_msl,weather_code"})
    d = d if isinstance(d, list) else [d]
    return pd.DataFrame([dict(temp=x["current"]["temperature_2m"], feels=x["current"]["apparent_temperature"],
                              humidity=x["current"]["relative_humidity_2m"], wind=x["current"]["wind_speed_10m"],
                              precip=x["current"]["precipitation"], pressure=x["current"]["pressure_msl"],
                              conditions=weather_label(x["current"]["weather_code"])) for x in d])


@st.cache_data(ttl=900, show_spinner=False)
def load_multi_aqi(lats, lons):
    d = get_json("https://air-quality-api.open-meteo.com/v1/air-quality", {
        "latitude": ",".join(map(str, lats)), "longitude": ",".join(map(str, lons)), "current": "us_aqi,pm2_5"})
    d = d if isinstance(d, list) else [d]
    return pd.DataFrame([dict(aqi=x["current"].get("us_aqi"), pm25=x["current"].get("pm2_5")) for x in d])


@st.cache_data(ttl=900, show_spinner=False)
def load_forecast(lat, lon):
    return get_json("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,pressure_msl,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,uv_index_max",
        "hourly": "temperature_2m,precipitation_probability"})


@st.cache_data(ttl=86400, show_spinner=False)
def geocode(name, country_code=None, count=8):
    p = {"name": name, "count": count, "language": "en", "format": "json"}
    if country_code:
        p["countryCode"] = country_code
    return get_json("https://geocoding-api.open-meteo.com/v1/search", p).get("results") or []


def _sparql(q):
    d = get_json("https://query.wikidata.org/sparql", {"query": q, "format": "json"}, timeout=40,
                 headers={"Accept": "application/sparql-results+json"})
    return [{k: v["value"] for k, v in b.items()} for b in d["results"]["bindings"]]


@st.cache_data(ttl=86400, show_spinner=False)
def load_cities_wd(iso3, limit=14):
    q = f"""SELECT ?cityLabel (MAX(?pop) AS ?population) (SAMPLE(?la) AS ?lat) (SAMPLE(?lo) AS ?lon) WHERE {{
      ?country wdt:P298 "{iso3}" .
      VALUES ?type {{ wd:Q515 wd:Q1549591 wd:Q1637706 }}
      ?city wdt:P31 ?type ; wdt:P17 ?country ; wdt:P1082 ?pop ; p:P625/psv:P625 ?cn .
      ?cn wikibase:geoLatitude ?la ; wikibase:geoLongitude ?lo .
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} GROUP BY ?city ?cityLabel ORDER BY DESC(?population) LIMIT {limit}"""
    rows = _sparql(q)
    if len(rows) < 4:  # broader fallback: any human settlement above 200k
        q2 = f"""SELECT ?cityLabel (MAX(?pop) AS ?population) (SAMPLE(?la) AS ?lat) (SAMPLE(?lo) AS ?lon) WHERE {{
          ?country wdt:P298 "{iso3}" .
          ?city wdt:P31/wdt:P279* wd:Q486972 ; wdt:P17 ?country ; wdt:P1082 ?pop ; p:P625/psv:P625 ?cn .
          FILTER(?pop > 200000)
          ?cn wikibase:geoLatitude ?la ; wikibase:geoLongitude ?lo .
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} GROUP BY ?city ?cityLabel ORDER BY DESC(?population) LIMIT {limit}"""
        try:
            rows = _sparql(q2) or rows
        except Exception:  # noqa: BLE001
            pass
    df = pd.DataFrame([dict(city=r["cityLabel"], population=float(r["population"]), lat=float(r["lat"]), lon=float(r["lon"])) for r in rows])
    if df.empty:
        raise RuntimeError("no cities found")
    return df.drop_duplicates("city").reset_index(drop=True)


# ---- markets ----------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def load_prices(tickers, period="3mo"):
    import yfinance as yf
    raw = yf.download(list(tickers), period=period, interval="1d", group_by="ticker", auto_adjust=True, progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            s = raw[t]["Close"].dropna()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            if len(s) >= 2:
                out[t] = s
        except Exception:  # noqa: BLE001
            continue
    if not out:
        raise RuntimeError("Yahoo Finance returned no data")
    return out


@st.cache_data(ttl=600, show_spinner=False)
def load_history(symbol, period="6mo"):
    import yfinance as yf
    interval = {"1d": "5m", "5d": "30m", "1mo": "1d"}.get(period, "1d")
    h = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if h.empty:
        raise RuntimeError(f"no data for {symbol}")
    h.index = pd.to_datetime(h.index).tz_localize(None)
    return h


def market_frame(period="3mo"):
    tick = tuple(sym for g in MARKETS.values() for sym in g.values())
    prices = safe(load_prices, {}, tick, period)
    rows, hist = [], {}
    for grp, items in MARKETS.items():
        for name, sym in items.items():
            s = prices.get(sym)
            if s is None or len(s) < 2:
                continue
            rows.append(dict(group=grp, name=name, symbol=sym, price=float(s.iloc[-1]),
                             chg_1d=(s.iloc[-1] / s.iloc[-2] - 1) * 100,
                             chg_1m=(s.iloc[-1] / s.iloc[max(0, len(s) - 22)] - 1) * 100,
                             chg_3m=(s.iloc[-1] / s.iloc[0] - 1) * 100))
            hist[name] = (s / s.iloc[0] - 1) * 100
    return pd.DataFrame(rows), pd.DataFrame(hist)


@st.cache_data(ttl=300, show_spinner=False)
def load_crypto():
    df = pd.DataFrame(get_json("https://api.coingecko.com/api/v3/coins/markets", {
        "vs_currency": "usd", "order": "market_cap_desc", "per_page": 20, "page": 1, "sparkline": "false",
        "price_change_percentage": "24h"}))
    return df[["name", "symbol", "current_price", "price_change_percentage_24h", "market_cap", "total_volume"]]


@st.cache_data(ttl=3600, show_spinner=False)
def load_fx(base="USD"):
    return pd.Series(get_json(f"https://open.er-api.com/v6/latest/{base}")["rates"]).sort_index()


# ---- space ------------------------------------------------------------------
@st.cache_data(ttl=8, show_spinner=False)
def load_iss():
    return get_json("https://api.wheretheiss.at/v1/satellites/25544")


@st.cache_data(ttl=120, show_spinner=False)
def load_iss_track(base):
    ts = ",".join(str(base + k * 600) for k in range(-4, 6))
    d = get_json("https://api.wheretheiss.at/v1/satellites/25544/positions", {"timestamps": ts, "units": "kilometers"})
    return pd.DataFrame([dict(lat=x["latitude"], lon=x["longitude"], t=x["timestamp"]) for x in d])


@st.cache_data(ttl=3600, show_spinner=False)
def load_astronauts():
    return pd.DataFrame(get_json("http://api.open-notify.org/astros.json")["people"]).rename(columns={"name": "astronaut", "craft": "spacecraft"})


@st.cache_data(ttl=3600, show_spinner=False)
def load_apod():
    return get_json("https://api.nasa.gov/planetary/apod", {"api_key": "DEMO_KEY"})


@st.cache_data(ttl=1800, show_spinner=False)
def load_launches():
    res = get_json("https://ll.thespacedevs.com/2.2.0/launch/upcoming/", {"limit": 10})["results"]
    return pd.DataFrame([dict(mission=r.get("name"), when=r.get("net"), status=(r.get("status") or {}).get("name"),
                              provider=(r.get("launch_service_provider") or {}).get("name"),
                              site=((r.get("pad") or {}).get("location") or {}).get("name")) for r in res])


@st.cache_data(ttl=3600, show_spinner=False)
def load_neo():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d = get_json("https://api.nasa.gov/neo/rest/v1/feed", {"start_date": today, "end_date": today, "api_key": "DEMO_KEY"})
    rows = []
    for day in d["near_earth_objects"].values():
        for o in day:
            ca = o["close_approach_data"][0]
            rows.append(dict(object=o["name"], diameter_m=o["estimated_diameter"]["meters"]["estimated_diameter_max"],
                             hazardous=o["is_potentially_hazardous_asteroid"], miss_lunar=float(ca["miss_distance"]["lunar"]),
                             speed_kmh=float(ca["relative_velocity"]["kilometers_per_hour"])))
    return pd.DataFrame(rows).sort_values("miss_lunar").reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def load_kp():
    d = get_json("https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json")
    df = pd.DataFrame(d[1:], columns=d[0]) if d and isinstance(d[0], list) else pd.DataFrame(d)
    col = "Kp" if "Kp" in df else "kp_index"
    df["time_tag"] = pd.to_datetime(df["time_tag"])
    df["kp"] = pd.to_numeric(df[col], errors="coerce")
    return df[["time_tag", "kp"]].tail(56)


@st.cache_data(ttl=600, show_spinner=False)
def load_swpc_alerts():
    return pd.DataFrame(get_json("https://services.swpc.noaa.gov/products/alerts.json")).head(8)


# ---- trending ---------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_wikipedia_top():
    skip = ("Special:", "Wikipedia:", "Portal:", "Help:", "File:", "Category:", "Talk:", "Template:")
    for back in (1, 2, 3):
        d = datetime.now(timezone.utc) - timedelta(days=back)
        try:
            items = get_json(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{d:%Y/%m/%d}")["items"][0]["articles"]
        except Exception:  # noqa: BLE001
            continue
        rows = [dict(article=a["article"].replace("_", " "), views=a["views"], url="https://en.wikipedia.org/wiki/" + a["article"])
                for a in items if a["article"] not in ("Main_Page", "-") and not a["article"].startswith(skip)][:25]
        return pd.DataFrame(rows), f"{d:%Y-%m-%d}"
    raise RuntimeError("Wikimedia unavailable")


@st.cache_data(ttl=600, show_spinner=False)
def load_hn():
    hits = get_json("https://hn.algolia.com/api/v1/search", {"tags": "front_page", "hitsPerPage": 25})["hits"]
    return pd.DataFrame([dict(title=h.get("title"), points=h.get("points", 0), comments=h.get("num_comments", 0),
                              url=h.get("url") or f"https://news.ycombinator.com/item?id={h['objectID']}") for h in hits])


@st.cache_data(ttl=1800, show_spinner=False)
def load_gtrends(geo):
    r = requests.get(f"https://trends.google.com/trending/rss?geo={geo}", headers=HEADERS, timeout=20)
    r.raise_for_status()
    rows = [dict(topic=strip_html(e.get("title", "")), searches=e.get("ht_approx_traffic", ""),
                 link="https://www.google.com/search?q=" + quote_plus(strip_html(e.get("title", "")))) for e in feedparser.parse(r.content).entries]
    return pd.DataFrame(rows)


@st.cache_data(ttl=900, show_spinner=False)
def load_windy(lat, lon, key):
    d = get_json("https://api.windy.com/webcams/api/v3/webcams", {"nearby": f"{lat},{lon},150", "limit": 12, "include": "images,location,urls"},
                 headers={"x-windy-api-key": key})
    return d.get("webcams", [])


# =============================================================================
# SHARED VISUALS
# =============================================================================
def render_news(df, n=30, summaries=True):
    if df is None or df.empty:
        st.info("No articles found.")
        return
    for r in df.head(n).itertuples():
        when = r.published.strftime("%d %b %H:%M UTC") if pd.notna(r.published) and r.published else ""
        st.markdown(f"**[{esc(r.title)}]({r.link})**  \n<span class='src-tag'>{r.source} · {when}</span>", unsafe_allow_html=True)
        if summaries and r.summary:
            st.caption(r.summary)


def hazard_map(q, ev, gd, region, height=560, layers=("Earthquakes", "Natural events (NASA)", "Disaster alerts (GDACS)")):
    fig = go.Figure()
    if "Earthquakes" in layers and q is not None and not q.empty:
        d = in_region(q, region)
        if not d.empty:
            fig.add_trace(go.Scattergeo(
                lat=d["lat"], lon=d["lon"], mode="markers", name="Earthquakes", hoverinfo="text",
                text=[f"M{m:.1f} · {p}" for m, p in zip(d["magnitude"], d["place"])],
                marker=dict(size=np.clip((d["magnitude"] - 1.5) * 4, 4, 40), color=d["magnitude"], colorscale="YlOrRd",
                            cmin=2.5, cmax=7, opacity=0.8, line=dict(width=0.5, color="rgba(0,0,0,.4)"))))
    if "Natural events (NASA)" in layers and ev is not None and not ev.empty:
        palette = px.colors.qualitative.Bold
        d = in_region(ev, region)
        for i, (cat, g) in enumerate(d.groupby("category")):
            fig.add_trace(go.Scattergeo(lat=g["lat"], lon=g["lon"], mode="markers", name=cat, hoverinfo="text", text=g["event"],
                                        marker=dict(size=9, symbol="diamond", color=palette[i % len(palette)], line=dict(width=0.6, color="white"))))
    if "Disaster alerts (GDACS)" in layers and gd is not None and not gd.empty:
        d = in_region(gd.dropna(subset=["lat", "lon"]), region)
        col = {"Green": "#22c55e", "Orange": "#f97316", "Red": "#ef4444"}
        for lvl, g in d.groupby("alert"):
            fig.add_trace(go.Scattergeo(lat=g["lat"], lon=g["lon"], mode="markers", name=f"GDACS {lvl}", hoverinfo="text",
                                        text=[f"{t} · {ti}" for t, ti in zip(g["type"], g["title"])],
                                        marker=dict(size=12, symbol="triangle-up", color=col.get(lvl, "#64748b"), line=dict(width=0.8, color="white"))))
    return style_geo(fig, region, height)


def choropleth_map(df, col, region, scale, height=560, rng=None, show_scale=True):
    d = df.dropna(subset=[col, "iso3"])
    if d.empty:
        return go.Figure()
    base = d[d["continent"] == region] if region != "World" and not d[d["continent"] == region].empty else d
    if rng is None:
        rng = (float(base[col].quantile(0.03)), float(base[col].quantile(0.97)))
    fig = px.choropleth(d, locations="iso3", color=col, hover_name="country", color_continuous_scale=scale,
                        range_color=rng, hover_data={col: ":,.2f", "iso3": False})
    fig.update_traces(marker_line_color="rgba(255,255,255,.35)", marker_line_width=0.4)
    fig.update_coloraxes(colorbar=dict(thickness=10, len=0.55, title=None), showscale=show_scale)
    return style_geo(fig, region, height)


def forecast_panel(lat, lon):
    fc = safe(load_forecast, None, round(float(lat), 3), round(float(lon), 3))
    if not fc:
        st.warning("Forecast unavailable.")
        return
    c, d, h = fc["current"], fc["daily"], fc["hourly"]
    aq = safe(load_multi_aqi, pd.DataFrame(), (round(float(lat), 3),), (round(float(lon), 3),))
    k = st.columns(6)
    kpi(k[0], "Now", f"{c['temperature_2m']:.0f}°C", weather_label(c["weather_code"]))
    kpi(k[1], "Feels like", f"{c['apparent_temperature']:.0f}°C")
    kpi(k[2], "Humidity", f"{c['relative_humidity_2m']}%")
    kpi(k[3], "Wind", f"{c['wind_speed_10m']:.0f} km/h")
    kpi(k[4], "Pressure", f"{c['pressure_msl']:.0f} hPa")
    v = aq["aqi"].iloc[0] if not aq.empty else None
    kpi(k[5], "Air quality (US AQI)", "—" if v is None or pd.isna(v) else f"{v:.0f}", aqi_label(v))
    days = pd.to_datetime(d["time"])
    fig = go.Figure()
    fig.add_bar(x=days, y=d["precipitation_sum"], name="Rain (mm)", marker_color="rgba(59,130,246,.45)", yaxis="y2")
    fig.add_scatter(x=days, y=d["temperature_2m_max"], name="Max °C", mode="lines+markers", line=dict(color="#ef4444", width=3))
    fig.add_scatter(x=days, y=d["temperature_2m_min"], name="Min °C", mode="lines+markers", line=dict(color="#3b82f6", width=3))
    clean_layout(fig, 330)
    fig.update_layout(yaxis=dict(title="°C"), yaxis2=dict(title="mm", overlaying="y", side="right", showgrid=False), title="7-day forecast")
    l, r = st.columns([3, 2])
    with l:
        plot(fig)
    with r:
        hh = pd.DataFrame({"time": pd.to_datetime(h["time"][:48]), "temp": h["temperature_2m"][:48], "rain_prob": h["precipitation_probability"][:48]})
        f2 = go.Figure()
        f2.add_scatter(x=hh["time"], y=hh["temp"], name="°C", line=dict(color="#f59e0b", width=2))
        f2.add_bar(x=hh["time"], y=hh["rain_prob"], name="Rain chance %", marker_color="rgba(59,130,246,.35)", yaxis="y2")
        clean_layout(f2, 330)
        f2.update_layout(title="Next 48 hours", yaxis2=dict(overlaying="y", side="right", range=[0, 100], showgrid=False))
        plot(f2)
    daily = pd.DataFrame({"Day": days.strftime("%a %d %b"), "Conditions": [weather_label(x) for x in d["weather_code"]],
                          "Max °C": d["temperature_2m_max"], "Min °C": d["temperature_2m_min"],
                          "Rain mm": d["precipitation_sum"], "UV max": d["uv_index_max"]})
    table(daily)


# =============================================================================
# PAGES
# =============================================================================
def world_clocks():
    try:
        from zoneinfo import ZoneInfo
        zones = [("New York", "America/New_York"), ("London", "Europe/London"), ("Moscow", "Europe/Moscow"), ("Dubai", "Asia/Dubai"),
                 ("Delhi", "Asia/Kolkata"), ("Singapore", "Asia/Singapore"), ("Tokyo", "Asia/Tokyo"), ("Sydney", "Australia/Sydney")]
        now = datetime.now(timezone.utc)
        for col, (n, z) in zip(st.columns(len(zones)), zones):
            t = now.astimezone(ZoneInfo(z))
            col.markdown(f"<div class='clock'><span>{n}</span><b>{t:%H:%M}</b><i>{t:%a %d %b}</i></div>", unsafe_allow_html=True)
    except Exception:  # noqa: BLE001
        pass


def page_overview():
    region = st.session_state.get("region", "World")
    now = datetime.now(timezone.utc)
    hero("🌍 Global Command Center", f"Live world monitor · {now:%A %d %B %Y, %H:%M UTC} · map focus: {region}")
    world_clocks()
    st.write("")
    wt = world_table()
    quakes = safe(load_quakes, pd.DataFrame(), "2.5_day")
    events = safe(load_eonet, pd.DataFrame())
    gdacs = safe(load_gdacs, pd.DataFrame())
    covid = safe(load_covid_global, {})
    crypto = safe(load_crypto, pd.DataFrame())
    mdf, mhist = market_frame("1mo")

    k = st.columns(4)
    kpi(k[0], "World population", fnum(wt["population"].sum()) if not wt.empty else "—", f"{len(wt)} countries & territories" if not wt.empty else "")
    kpi(k[1], "Earthquakes M2.5+ (24h)", len(quakes) if not quakes.empty else "—",
        f"Strongest M{quakes['magnitude'].max():.1f}" if not quakes.empty else "")
    kpi(k[2], "Active natural events", len(events) if not events.empty else "—", "NASA EONET")
    red = int(gdacs["alert"].isin(["Orange", "Red"]).sum()) if not gdacs.empty else None
    kpi(k[3], "High-level disaster alerts", red if red is not None else "—", "GDACS orange / red", "down" if red else "")
    k = st.columns(4)
    kpi(k[0], "COVID-19 cumulative cases", fnum(covid.get("cases")) if covid else "—", f"+{fnum(covid.get('todayCases'), 0)} today" if covid else "")
    if not crypto.empty and (crypto["symbol"] == "btc").any():
        b = crypto[crypto["symbol"] == "btc"].iloc[0]
        kpi(k[1], "Bitcoin", f"${b['current_price']:,.0f}", f"{b['price_change_percentage_24h']:+.2f}% 24h", "up" if b["price_change_percentage_24h"] > 0 else "down")
    else:
        kpi(k[1], "Bitcoin", "—")
    for col, nm in zip(k[2:], ["S&P 500", "Gold"]):
        r = mdf[mdf["name"] == nm] if not mdf.empty else pd.DataFrame()
        if r.empty:
            kpi(col, nm, "—")
        else:
            r = r.iloc[0]
            kpi(col, nm, f"{r['price']:,.2f}", f"{r['chg_1d']:+.2f}% today", "up" if r["chg_1d"] > 0 else "down")

    st.subheader(f"🗺️ Hazard map — {region}")
    plot(hazard_map(quakes, events, gdacs, region, 540))
    st.caption("Circles: earthquakes (size/colour = magnitude) · Diamonds: NASA natural events · Triangles: GDACS disaster alerts. Change region in the sidebar.")

    l, r = st.columns([3, 2])
    with l:
        st.subheader("📰 Top headlines")
        news = safe(load_news, pd.DataFrame(), "World", ("BBC", "Al Jazeera", "NPR", "The Guardian", "Sky News"))
        render_news(news, 9, summaries=False)
    with r:
        st.subheader("🦠 Latest health alerts (WHO)")
        who = safe(load_who_don, pd.DataFrame())
        if who.empty:
            st.info("WHO feed unavailable.")
        else:
            for x in who.head(6).itertuples():
                st.markdown(f"**[{esc(x.title)}]({x.link})**  \n<span class='src-tag'>{x.published:%d %b %Y}</span>" if pd.notna(x.published) else f"[{esc(x.title)}]({x.link})", unsafe_allow_html=True)
        if not gdacs.empty:
            st.subheader("🚨 Disaster alerts (GDACS)")
            sel = gdacs[gdacs["alert"].isin(["Orange", "Red"])].head(6)
            for x in (sel if not sel.empty else gdacs.head(5)).itertuples():
                colr = {"Red": "#ef4444", "Orange": "#f97316"}.get(x.alert, "#22c55e")
                st.markdown(f"<span class='chip' style='background:{colr}'>{x.alert}</span>[{esc(x.title)}]({x.link})", unsafe_allow_html=True)

    st.subheader("📈 Markets today")
    if mdf.empty:
        st.info("Market data unavailable right now.")
    else:
        fig = px.bar(mdf.sort_values("chg_1d"), x="chg_1d", y="name", orientation="h", color="chg_1d",
                     color_continuous_scale="RdYlGn", color_continuous_midpoint=0, labels={"chg_1d": "1-day change (%)", "name": ""})
        clean_layout(fig, 480).update_layout(coloraxis_showscale=False)
        plot(fig)

    if not wt.empty:
        st.subheader("🌐 Continent snapshot")
        g = wt[wt["continent"] != "Antarctica"].groupby("continent").agg(
            countries=("country", "count"), population=("population", "sum"), area_km2=("area", "sum"),
            gdp_usd=("gdp", "sum"), covid_cases=("cases", "sum")).reset_index()
        a, b = st.columns([2, 3])
        with a:
            fig = px.pie(g, names="continent", values="population", hole=0.55)
            clean_layout(fig, 320).update_layout(title="Share of world population")
            plot(fig)
        with b:
            table(g.assign(population=g["population"].map(fnum), area_km2=g["area_km2"].map(fnum),
                           gdp_usd=g["gdp_usd"].map(fnum), covid_cases=g["covid_cases"].map(fnum)))


def page_maps():
    region = st.session_state.get("region", "World")
    hero("🗺️ Continents & Maps", "Choropleth maps of 19 global indicators — focus one continent or compare all six side by side")
    wt = world_table()
    if wt.empty:
        st.error("Country data is unavailable right now (REST Countries). Try Refresh in the sidebar.")
        return
    c1, c2 = st.columns([3, 1])
    label = c1.selectbox("Indicator", list(MAP_METRICS), index=0)
    col, scale = MAP_METRICS[label]
    c2.caption(f"Region: **{region}** (change in sidebar)")
    if wt[col].notna().sum() == 0:
        st.warning("This indicator's source is unavailable right now. Choose another.")
        return
    plot(choropleth_map(wt, col, region, scale, 580))
    view = wt if region == "World" else wt[wt["continent"] == region]
    view = view.dropna(subset=[col])
    a, b = st.columns(2)
    with a:
        top = view.nlargest(12, col)
        fig = px.bar(top.iloc[::-1], x=col, y="country", orientation="h", color_discrete_sequence=["#3b82f6"])
        clean_layout(fig, 400).update_layout(title=f"Highest — {region}", yaxis_title="", xaxis_title=label)
        plot(fig)
    with b:
        bot = view.nsmallest(12, col)
        fig = px.bar(bot.iloc[::-1], x=col, y="country", orientation="h", color_discrete_sequence=["#f59e0b"])
        clean_layout(fig, 400).update_layout(title=f"Lowest — {region}", yaxis_title="", xaxis_title=label)
        plot(fig)

    st.subheader("🌐 All continents side by side")
    d = wt.dropna(subset=[col])
    rng = (float(d[col].quantile(0.03)), float(d[col].quantile(0.97)))
    conts = [r for r in REGIONS if r != "World"]
    cols = st.columns(3)
    for i, r in enumerate(conts):
        with cols[i % 3]:
            st.markdown(f"**{r}**")
            plot(choropleth_map(wt, col, r, scale, 300, rng=rng, show_scale=False))
    st.caption(f"Shared colour scale for '{label}' across all six maps (3rd–97th percentile).")

    st.subheader("📊 Continent comparison")
    dd = wt[wt["continent"] != "Antarctica"].dropna(subset=[col])
    a, b = st.columns(2)
    with a:
        fig = px.box(dd, x="continent", y=col, color="continent", points="all", hover_name="country")
        clean_layout(fig, 380).update_layout(showlegend=False, xaxis_title="", yaxis_title=label, title="Distribution by continent")
        plot(fig)
    with b:
        agg = dd.groupby("continent")[col].median().reset_index().sort_values(col)
        fig = px.bar(agg, x=col, y="continent", orientation="h", color="continent")
        clean_layout(fig, 380).update_layout(showlegend=False, yaxis_title="", xaxis_title=f"Median — {label}", title="Median by continent")
        plot(fig)
    tm = wt[(wt["continent"] != "Antarctica")].dropna(subset=["population"]).copy()
    tm = tm[tm["population"] > 0]
    fig = px.treemap(tm, path=["continent", "subregion", "country"], values="population", color="continent")
    clean_layout(fig, 520).update_layout(title="World population — continent › sub-region › country")
    plot(fig)


def page_country():
    hero("🏳️ Country Explorer", "Profile, economy, cities, weather, news and health for any country in the world")
    wt = world_table()
    if wt.empty:
        st.error("Country data is unavailable right now. Try Refresh in the sidebar.")
        return
    names = wt["country"].tolist()
    name = st.selectbox("Choose a country (type to search)", names, index=names.index("United States") if "United States" in names else 0, key="country_sel")
    row = wt[wt["country"] == name].iloc[0]
    iso2, iso3 = row["iso2"], row["iso3"]
    det = safe(load_country_detail, {}, iso3)

    h1, h2 = st.columns([1, 6])
    with h1:
        if row["flag"]:
            st.image(row["flag"], width=130)
    with h2:
        st.markdown(f"## {name}")
        st.caption(f"{row['official']} · {row['continent']} · {row['subregion']}")
    k = st.columns(5)
    kpi(k[0], "Population", fnum(row["population"]), f"#{int(wt['population'].rank(ascending=False, method='min')[row.name])} worldwide")
    kpi(k[1], "Area (km²)", fnum(row["area"], 0))
    kpi(k[2], "Density (/km²)", fnum(row["density"], 0))
    kpi(k[3], "Capital", row["capital"] or "—")
    gp = row["gdp_pc"]
    kpi(k[4], "GDP per capita", f"${fnum(gp)}" if pd.notna(gp) else "—",
        f"#{int(wt['gdp_pc'].rank(ascending=False, method='min')[row.name])} worldwide" if pd.notna(gp) else "")

    # cities
    cities = safe(load_cities_wd, pd.DataFrame(columns=["city", "population", "lat", "lon"]), iso3)
    cap_ll = (det.get("capitalInfo") or {}).get("latlng")
    if row["capital"] and cap_ll and (cities.empty or row["capital"] not in set(cities["city"])):
        cities = pd.concat([cities, pd.DataFrame([dict(city=row["capital"], population=np.nan, lat=cap_ll[0], lon=cap_ll[1])])], ignore_index=True)
    q = st.text_input("➕ Add any other city in this country", placeholder="e.g. a smaller city or town", key="city_search")
    if q:
        for g in safe(geocode, [], q, iso2)[:1]:
            cities = pd.concat([cities, pd.DataFrame([dict(city=g["name"], population=g.get("population") or np.nan, lat=g["latitude"], lon=g["longitude"])])], ignore_index=True)
    cities = cities.drop_duplicates("city").reset_index(drop=True)
    focus = None
    if not cities.empty:
        default = list(cities["city"]).index(row["capital"]) if row["capital"] in set(cities["city"]) else 0
        focus = st.selectbox("Focus city", list(cities["city"]), index=default, key="focus_city")

    t1, t2, t3, t4, t5 = st.tabs(["Overview", "Economy & society", "Cities & weather", "News", "Health"])

    with t1:
        l, r = st.columns([2, 3])
        with l:
            langs = ", ".join((det.get("languages") or {}).values()) or "—"
            cur = ", ".join(f"{v.get('name')} ({v.get('symbol', '')})" for v in (det.get("currencies") or {}).values()) or "—"
            idd = det.get("idd") or {}
            code = (idd.get("root") or "") + ((idd.get("suffixes") or [""])[0] if len(idd.get("suffixes") or []) == 1 else "")
            borders = [wt.loc[wt["iso3"] == b, "country"].iloc[0] for b in (det.get("borders") or []) if (wt["iso3"] == b).any()]
            facts = {
                "Capital": row["capital"] or "—", "Languages": langs, "Currency": cur,
                "Time zones": ", ".join((det.get("timezones") or [])[:4]) or "—", "Calling code": code or "—",
                "Internet domain": ", ".join(det.get("tld") or []) or "—", "Drives on": (det.get("car") or {}).get("side", "—"),
                "UN member": "Yes" if det.get("unMember") else "No", "Landlocked": "Yes" if det.get("landlocked") else "No",
                "Borders": ", ".join(borders) or "None (island / no land borders)",
            }
            for kx, vx in facts.items():
                st.markdown(f"**{kx}:** {vx}")
            gm = (det.get("maps") or {}).get("googleMaps")
            if gm:
                st.link_button("Open in Google Maps", gm)
        with r:
            codes = [iso3] + [b for b in (det.get("borders") or [])]
            fig = go.Figure(go.Choropleth(locations=codes, z=[1] + [0] * (len(codes) - 1), zmin=0, zmax=1,
                                          colorscale=[[0, "rgba(140,150,165,.28)"], [1, "rgba(37,99,235,.7)"]], showscale=False,
                                          marker_line_color="white", marker_line_width=0.6, hoverinfo="location"))
            if not cities.empty:
                fig.add_trace(go.Scattergeo(lat=cities["lat"], lon=cities["lon"], text=cities["city"], mode="markers+text", textposition="top center",
                                            marker=dict(size=7, color="#f59e0b", line=dict(width=1, color="white")), hoverinfo="text", showlegend=False))
            style_geo(fig, "World", 480, detail=True)
            fig.update_geos(fitbounds="locations")
            plot(fig)

    with t2:
        keys = st.multiselect("Indicators", list(WB_IND), default=["gdp_pc", "gdp_growth", "life_exp", "inflation", "unemployment", "internet", "mobile", "co2_pc"],
                              format_func=lambda x: WB_IND[x][1])
        cols = st.columns(2)
        for i, kx in enumerate(keys):
            s = safe(load_wb_multi, pd.DataFrame(), (iso3,), WB_IND[kx][0], 1990)
            with cols[i % 2]:
                if s.empty:
                    st.caption(f"{WB_IND[kx][1]}: no data")
                    continue
                fig = px.area(s, x="year", y="value", color_discrete_sequence=["#3b82f6"])
                clean_layout(fig, 250).update_layout(title=f"{WB_IND[kx][1]} — latest {s['value'].iloc[-1]:,.2f} ({int(s['year'].iloc[-1])})", yaxis_title="", xaxis_title="")
                plot(fig)
        st.caption("Source: World Bank Open Data")

    with t3:
        if cities.empty:
            st.info("No city list available for this country right now. Try the 'Add any other city' box above.")
        else:
            lim = cities.head(16)
            wx = safe(load_multi_weather, pd.DataFrame(), tuple(round(x, 3) for x in lim["lat"]), tuple(round(x, 3) for x in lim["lon"]))
            if not wx.empty and len(wx) == len(lim):
                cw = pd.concat([lim.reset_index(drop=True), wx], axis=1)
                fig = px.scatter_geo(cw, lat="lat", lon="lon", color="temp", text="city", hover_name="city",
                                     hover_data={"conditions": True, "humidity": True, "wind": True, "lat": False, "lon": False},
                                     color_continuous_scale="RdYlBu_r", size_max=14)
                fig.update_traces(marker=dict(size=14, line=dict(width=1, color="white")), textposition="top center")
                style_geo(fig, "World", 460, detail=True)
                fig.update_geos(fitbounds="locations")
                fig.update_coloraxes(colorbar=dict(title="°C", thickness=10, len=0.5))
                plot(fig)
                table(cw[["city", "conditions", "temp", "feels", "humidity", "wind", "population"]].rename(
                    columns={"temp": "°C", "feels": "Feels °C", "humidity": "Humidity %", "wind": "Wind km/h"}))
            if focus:
                fr = cities[cities["city"] == focus].iloc[0]
                st.subheader(f"Forecast — {focus}")
                forecast_panel(fr["lat"], fr["lon"])

    with t4:
        mode = st.radio("Show", ["Top stories in this country", f"All news about {name}", f"News about {focus or 'a city'}"], horizontal=True, key="cnews")
        if mode.startswith("Top"):
            render_news(safe(load_gnews_top, pd.DataFrame(), iso2), 30, False)
        elif mode.startswith("All"):
            render_news(safe(load_gnews, pd.DataFrame(), f'"{name}"', ("en-US", "US", "US:en"), "3d"), 30, False)
        elif focus:
            render_news(safe(load_gnews, pd.DataFrame(), f'"{focus}" {name}', ("en-US", "US", "US:en"), "7d"), 30, False)

    with t5:
        k = st.columns(4)
        kpi(k[0], "COVID-19 cases", fnum(row["cases"]), f"{fnum(row['cases_pm'], 0)} per million")
        kpi(k[1], "COVID-19 deaths", fnum(row["deaths"]), f"{fnum(row['deaths_pm'], 0)} per million")
        kpi(k[2], "Life expectancy", f"{row['life_exp']:.1f} yrs" if pd.notna(row["life_exp"]) else "—")
        kpi(k[3], "Health spending", f"{row['health_exp']:.1f}% GDP" if pd.notna(row["health_exp"]) else "—")
        hist = safe(load_covid_history, pd.DataFrame(), iso3)
        if not hist.empty:
            fig = px.area(hist, x="date", y="new_cases_7d", color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 280).update_layout(title="COVID-19 daily new cases (7-day average)", yaxis_title="", xaxis_title="")
            plot(fig)
            st.caption("Historical series from Johns Hopkins via disease.sh — many countries stopped reporting in 2023.")
        st.subheader(f"Outbreak & disease news — {name}")
        render_news(safe(load_gnews, pd.DataFrame(), f"{name} (outbreak OR epidemic OR disease OR virus)", ("en-US", "US", "US:en"), "30d"), 12, False)
        who = safe(load_who_don, pd.DataFrame())
        ob = parse_outbreaks(who, wt)
        if not ob.empty and (ob["iso3"] == iso3).any():
            st.subheader("WHO Disease Outbreak News mentioning this country")
            for x in ob[ob["iso3"] == iso3].itertuples():
                st.markdown(f"**[{esc(x.title)}]({x.link})**")


def page_compare():
    hero("⚖️ Compare Countries", "Side-by-side time series, rankings, bubble charts, radar and percentile heat-maps")
    wt = world_table()
    if wt.empty:
        st.error("Country data unavailable right now.")
        return
    names = wt["country"].tolist()
    default = [c for c in ["United States", "China", "India", "Germany", "Brazil", "Nigeria"] if c in names]
    sel = st.multiselect("Countries to compare (2–8)", names, default=default, max_selections=8)
    if len(sel) < 2:
        st.info("Pick at least two countries.")
        return
    sdf = wt[wt["country"].isin(sel)]
    iso = tuple(sdf["iso3"])
    c1, c2 = st.columns([3, 1])
    ind = c1.selectbox("Indicator over time", list(WB_IND), index=1, format_func=lambda x: WB_IND[x][1])
    start = c2.slider("From year", 1960, 2020, 1995)
    ts = safe(load_wb_multi, pd.DataFrame(), iso, WB_IND[ind][0], start)
    a, b = st.columns([3, 2])
    with a:
        if ts.empty:
            st.warning("Time series unavailable.")
        else:
            fig = px.line(ts, x="year", y="value", color="country", markers=False)
            clean_layout(fig, 400).update_layout(title=WB_IND[ind][1], xaxis_title="", yaxis_title="")
            plot(fig)
    with b:
        lat = sdf.dropna(subset=[ind]).sort_values(ind)
        fig = px.bar(lat, x=ind, y="country", orientation="h", color="country")
        clean_layout(fig, 400).update_layout(title="Latest value", showlegend=False, yaxis_title="", xaxis_title="")
        plot(fig)

    st.subheader("🫧 World map of relationships")
    labels = {**{k: v[1] for k, v in WB_IND.items()}, "population": "Population", "density": "Population density", "cases_pm": "COVID-19 cases / million"}
    x1, x2, x3 = st.columns([2, 2, 1])
    xc = x1.selectbox("X axis", list(labels), index=list(labels).index("gdp_pc"), format_func=lambda x: labels[x])
    yc = x2.selectbox("Y axis", list(labels), index=list(labels).index("life_exp"), format_func=lambda x: labels[x])
    logx = x3.checkbox("Log X", value=True)
    bd = wt.dropna(subset=[xc, yc, "population"])
    bd = bd[bd["continent"] != "Antarctica"]
    if not bd.empty:
        fig = px.scatter(bd, x=xc, y=yc, size="population", color="continent", hover_name="country", size_max=55, log_x=logx and (bd[xc] > 0).all(), opacity=0.7)
        pick = bd[bd["country"].isin(sel)]
        fig.add_trace(go.Scatter(x=pick[xc], y=pick[yc], mode="text", text=pick["country"], textposition="top center", showlegend=False))
        clean_layout(fig, 500).update_layout(xaxis_title=labels[xc], yaxis_title=labels[yc])
        plot(fig)

    st.subheader("🕸️ Profile radar & percentile heat-map")
    radar_keys = st.multiselect("Indicators", list(HIGHER_BETTER), default=["gdp_pc", "life_exp", "internet", "mobile", "electricity", "infant_mort", "unemployment", "inflation"],
                                format_func=lambda x: WB_IND[x][1])
    if len(radar_keys) >= 3:
        pct = pd.DataFrame(index=wt.index)
        for kx in radar_keys:
            p = wt[kx].rank(pct=True) * 100
            pct[kx] = p if HIGHER_BETTER[kx] else 100 - p
        pct["country"] = wt["country"]
        pp = pct[pct["country"].isin(sel)].set_index("country")
        l, r = st.columns(2)
        with l:
            fig = go.Figure()
            for cn, rowp in pp.iterrows():
                vals = [rowp[kx] if pd.notna(rowp[kx]) else 0 for kx in radar_keys]
                fig.add_trace(go.Scatterpolar(r=vals + vals[:1], theta=[WB_IND[kx][1] for kx in radar_keys] + [WB_IND[radar_keys[0]][1]], fill="toself", name=cn, opacity=0.55))
            fig.update_layout(polar=dict(radialaxis=dict(range=[0, 100])), height=460, margin=dict(l=40, r=40, t=30, b=30),
                              paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=-0.1), title="Percentile vs all countries (higher = better)")
            plot(fig)
        with r:
            fig = px.imshow(pp[radar_keys].rename(columns={k2: WB_IND[k2][1] for k2 in radar_keys}), text_auto=".0f", color_continuous_scale="RdYlGn", zmin=0, zmax=100, aspect="auto")
            clean_layout(fig, 460).update_layout(title="Percentile heat-map", coloraxis_showscale=False)
            plot(fig)

    st.subheader("📋 Data table")
    cols = ["country", "continent", "population", "area", "gdp", "gdp_pc", "life_exp", "inflation", "unemployment", "internet", "mobile", "cases_pm", "deaths_pm"]
    table(sdf[cols].rename(columns={"gdp_pc": "GDP/capita", "life_exp": "Life exp.", "cases_pm": "COVID cases/M", "deaths_pm": "COVID deaths/M"}))


def page_health():
    hero("🦠 Health & Outbreak Watch", "WHO outbreak news, disease radar for any country, CDC travel notices and COVID-19 statistics")
    wt = world_table()
    region = st.session_state.get("region", "World")
    who = safe(load_who_don, pd.DataFrame())
    ob = parse_outbreaks(who, wt) if not wt.empty else pd.DataFrame()

    st.subheader("🚨 WHO Disease Outbreak News")
    l, r = st.columns([3, 2])
    with l:
        if who.empty:
            st.info("WHO feed unavailable right now.")
        else:
            kw = st.text_input("Filter outbreaks (disease or country)", placeholder="e.g. cholera, Congo, avian")
            w = who[who["title"].str.contains(kw, case=False, na=False)] if kw else who
            for x in w.head(15).itertuples():
                st.markdown(f"**[{esc(x.title)}]({x.link})**  \n<span class='src-tag'>{x.published:%d %b %Y}</span>" if pd.notna(x.published) else f"[{esc(x.title)}]({x.link})", unsafe_allow_html=True)
                if x.summary:
                    st.caption(x.summary[:240] + "…")
    with r:
        if not ob.empty:
            cnt = ob.groupby(["country", "iso3", "lat", "lon"]).agg(reports=("title", "count"), diseases=("disease", lambda s: ", ".join(sorted(set(s))[:3]))).reset_index()
            fig = px.scatter_geo(cnt, lat="lat", lon="lon", size="reports", hover_name="country", hover_data={"diseases": True, "lat": False, "lon": False},
                                 color_discrete_sequence=["#ef4444"], size_max=26)
            style_geo(fig, region, 360)
            plot(fig)
            dis = ob["disease"].value_counts().head(8).reset_index()
            dis.columns = ["disease", "reports"]
            fig = px.bar(dis.iloc[::-1], x="reports", y="disease", orientation="h", color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 260).update_layout(yaxis_title="", title="Most-reported diseases")
            plot(fig)
        else:
            st.caption("Outbreak map appears when WHO titles can be matched to countries.")

    st.subheader("🔎 Disease radar — search any disease in any country")
    c1, c2, c3 = st.columns([2, 2, 1])
    dis = c1.selectbox("Disease", DISEASES, index=0)
    if dis == "Custom…":
        dis = c1.text_input("Custom disease", "monkeypox")
    names = ["Anywhere"] + (wt["country"].tolist() if not wt.empty else [])
    ctry = c2.selectbox("Country", names, index=names.index("Russia") if "Russia" in names else 0)
    win = c3.selectbox("Period", list(WHEN)[1:], index=2)
    query = f"{dis} (outbreak OR cases OR epidemic)" + ("" if ctry == "Anywhere" else f' "{ctry}"')
    news = safe(load_gnews, pd.DataFrame(), query, ("en-US", "US", "US:en"), WHEN[win], 60)
    if news.empty:
        st.info("No recent coverage found for this combination.")
    else:
        a, b = st.columns([3, 2])
        with a:
            st.caption(f"{len(news)} recent articles · query: {query}")
            render_news(news, 12, False)
        with b:
            daily = news.dropna(subset=["published"]).assign(day=lambda d: d["published"].dt.floor("D")).groupby("day").size().reset_index(name="articles")
            if not daily.empty:
                fig = px.bar(daily, x="day", y="articles", color_discrete_sequence=["#f59e0b"])
                clean_layout(fig, 240).update_layout(title="Media attention over time", xaxis_title="", yaxis_title="")
                plot(fig)
            src = news["source"].value_counts().head(8).reset_index()
            src.columns = ["source", "articles"]
            fig = px.bar(src.iloc[::-1], x="articles", y="source", orientation="h")
            clean_layout(fig, 260).update_layout(title="Top sources", yaxis_title="")
            plot(fig)

    st.subheader("🧳 CDC travel health notices")
    cdc = safe(load_rss, pd.DataFrame(), "https://wwwnc.cdc.gov/travel/rss/notices.xml", "CDC", 15)
    render_news(cdc, 10, True) if not cdc.empty else st.info("CDC feed unavailable.")

    st.subheader("😷 COVID-19 statistics")
    cv = safe(load_covid_global, {})
    if cv:
        k = st.columns(5)
        kpi(k[0], "Total cases", fnum(cv["cases"]), f"+{fnum(cv['todayCases'], 0)} today")
        kpi(k[1], "Total deaths", fnum(cv["deaths"]), f"+{fnum(cv['todayDeaths'], 0)} today")
        kpi(k[2], "Active", fnum(cv["active"]))
        kpi(k[3], "Recovered", fnum(cv["recovered"]))
        kpi(k[4], "Countries reporting", cv.get("affectedCountries", "—"))
    if not wt.empty and wt["cases_pm"].notna().any():
        metric = st.radio("Map metric", ["cases_pm", "deaths_pm", "cases", "deaths"], horizontal=True,
                          format_func={"cases_pm": "Cases / million", "deaths_pm": "Deaths / million", "cases": "Total cases", "deaths": "Total deaths"}.get)
        plot(choropleth_map(wt, metric, region, "Reds", 480))
        a, b = st.columns(2)
        with a:
            g = wt[wt["continent"] != "Antarctica"].groupby("continent")[["cases", "deaths"]].sum().reset_index()
            fig = px.bar(g.sort_values("cases"), x="cases", y="continent", orientation="h", color="continent")
            clean_layout(fig, 320).update_layout(showlegend=False, yaxis_title="", title="Cumulative cases by continent")
            plot(fig)
        with b:
            top = (wt if region == "World" else wt[wt["continent"] == region]).nlargest(12, "cases")
            fig = px.bar(top.iloc[::-1], x="cases", y="country", orientation="h", color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 320).update_layout(yaxis_title="", title=f"Most cases — {region}")
            plot(fig)
    gh = safe(load_covid_history, pd.DataFrame(), "all")
    if not gh.empty:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Scatter(x=gh["date"], y=gh["new_cases_7d"], name="New cases (7-day avg)", line=dict(color="#ef4444")), secondary_y=False)
        fig.add_trace(go.Scatter(x=gh["date"], y=gh["new_deaths_7d"], name="New deaths (7-day avg)", line=dict(color="#64748b")), secondary_y=True)
        clean_layout(fig, 340).update_layout(title="Global COVID-19 trend")
        plot(fig)
        st.caption("Johns Hopkins historical series were frozen in 2023; present-day figures come from country reporting aggregated by Worldometer via disease.sh.")


def page_news():
    hero("📰 News Room", "Curated global feeds, search any topic or country, and regional desks — all live")
    mode = st.radio("Mode", ["Top feeds", "Search any topic", "Regions & country desk"], horizontal=True, label_visibility="collapsed")
    if mode == "Top feeds":
        c1, c2, c3 = st.columns([1, 2, 2])
        cat = c1.selectbox("Category", list(NEWS_FEEDS))
        avail = list(NEWS_FEEDS[cat])
        chosen = c2.multiselect("Sources", avail, default=avail)
        kw = c3.text_input("Filter by keyword")
        df = safe(load_news, pd.DataFrame(), cat, tuple(chosen)) if chosen else pd.DataFrame()
        if not df.empty and kw:
            df = df[df["title"].str.contains(kw, case=False, na=False) | df["summary"].str.contains(kw, case=False, na=False)]
        st.caption(f"{len(df)} articles")
        render_news(df, 60)
    elif mode == "Search any topic":
        c1, c2, c3 = st.columns([3, 2, 1])
        q = c1.text_input("Search the world's news", "world economy")
        ed = c2.selectbox("Edition", list(EDITIONS))
        wh = c3.selectbox("Period", list(WHEN), index=2)
        if q:
            df = safe(load_gnews, pd.DataFrame(), q, EDITIONS[ed], WHEN[wh], 60)
            st.caption(f"{len(df)} articles")
            a, b = st.columns([3, 1])
            with a:
                render_news(df, 40, False)
            with b:
                if not df.empty:
                    s = df["source"].value_counts().head(10).reset_index()
                    s.columns = ["source", "articles"]
                    fig = px.bar(s.iloc[::-1], x="articles", y="source", orientation="h")
                    clean_layout(fig, 360).update_layout(yaxis_title="", title="Sources")
                    plot(fig)
    else:
        wt = world_table()
        a, b = st.columns(2)
        with a:
            reg = st.selectbox("Regional desk", ["Africa", "Asia", "Europe", "Middle East", "North America", "Latin America", "Oceania", "Arctic", "Global economy"])
            st.subheader(reg)
            render_news(safe(load_gnews, pd.DataFrame(), f'"{reg}"', ("en-US", "US", "US:en"), "1d", 40), 25, False)
        with b:
            names = wt["country"].tolist() if not wt.empty else []
            if names:
                cn = st.selectbox("Country desk", names, index=names.index("United Kingdom") if "United Kingdom" in names else 0)
                iso2 = wt.loc[wt["country"] == cn, "iso2"].iloc[0]
                st.subheader(cn)
                render_news(safe(load_gnews_top, pd.DataFrame(), iso2), 25, False)
            else:
                st.info("Country list unavailable.")


def page_markets():
    hero("📈 Markets & Currencies", "Global indices, commodities, crypto, FX converter, and an explorer for any ticker")
    mdf, mhist = market_frame("3mo")
    if mdf.empty:
        st.warning("Market data unavailable (Yahoo Finance may be rate-limiting). Click Refresh in a minute.")
    else:
        for grp in MARKETS:
            g = mdf[mdf["group"] == grp]
            if g.empty:
                continue
            st.markdown(f"**{grp}**")
            cols = st.columns(4)
            for i, r in enumerate(g.itertuples()):
                kpi(cols[i % 4], r.name, f"{r.price:,.2f}", f"{r.chg_1d:+.2f}% today · {r.chg_1m:+.1f}% 1M", "up" if r.chg_1d > 0 else "down")
        names = list(mhist.columns)
        pick = st.multiselect("Relative performance, last 3 months (%)", names, default=[n for n in ["S&P 500", "FTSE 100", "Nikkei 225", "Gold", "Crude Oil WTI"] if n in names])
        if pick:
            fig = px.line(mhist[pick])
            fig.update_traces(connectgaps=True)
            clean_layout(fig, 380).update_layout(xaxis_title="", yaxis_title="% change", legend_title="")
            plot(fig)
        fig = px.bar(mdf.sort_values("chg_1m"), x="chg_1m", y="name", orientation="h", color="group")
        clean_layout(fig, 560).update_layout(title="1-month change by market (%)", yaxis_title="", xaxis_title="")
        plot(fig)

    st.subheader("🔍 Ticker explorer")
    c1, c2 = st.columns([3, 1])
    sym = c1.text_input("Yahoo Finance symbol", "AAPL", help="Examples: MSFT · 7203.T (Toyota) · 0700.HK (Tencent) · BTC-USD · EURUSD=X · ^GSPC")
    per = c2.selectbox("Period", ["1mo", "6mo", "1y", "5y"], index=1)
    h = safe(load_history, pd.DataFrame(), sym.strip(), per) if sym.strip() else pd.DataFrame()
    if h.empty:
        st.info("No data for that symbol.")
    else:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(x=h.index, open=h["Open"], high=h["High"], low=h["Low"], close=h["Close"], name=sym.upper()), row=1, col=1)
        fig.add_trace(go.Scatter(x=h.index, y=h["Close"].rolling(20).mean(), name="MA20", line=dict(width=1.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=h.index, y=h["Close"].rolling(50).mean(), name="MA50", line=dict(width=1.5)), row=1, col=1)
        fig.add_trace(go.Bar(x=h.index, y=h["Volume"], name="Volume", marker_color="rgba(100,116,139,.5)"), row=2, col=1)
        clean_layout(fig, 560).update_layout(xaxis_rangeslider_visible=False)
        plot(fig)

    st.subheader("🪙 Cryptocurrencies")
    crypto = safe(load_crypto, pd.DataFrame())
    if crypto.empty:
        st.info("Crypto data unavailable (CoinGecko rate limit).")
    else:
        a, b = st.columns([3, 2])
        with a:
            table(crypto.rename(columns={"name": "Coin", "symbol": "Ticker", "current_price": "Price (USD)", "price_change_percentage_24h": "24h %",
                                         "market_cap": "Market cap", "total_volume": "24h volume"}),
                  column_config={"Price (USD)": st.column_config.NumberColumn(format="$%.4f"), "24h %": st.column_config.NumberColumn(format="%.2f%%"),
                                 "Market cap": st.column_config.NumberColumn(format="$%d"), "24h volume": st.column_config.NumberColumn(format="$%d")})
        with b:
            fig = px.bar(crypto.sort_values("price_change_percentage_24h"), x="price_change_percentage_24h", y="name", orientation="h",
                         color="price_change_percentage_24h", color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
            clean_layout(fig, 560).update_layout(coloraxis_showscale=False, yaxis_title="", xaxis_title="24h change %")
            plot(fig)

    st.subheader("💱 Currency converter & cross-rates")
    cur = ["USD", "EUR", "GBP", "JPY", "CNY", "INR", "AUD", "CAD", "CHF", "SGD", "MYR", "KRW", "BRL", "MXN", "ZAR", "AED", "TRY", "THB", "IDR", "RUB"]
    fx = safe(load_fx, pd.Series(dtype=float), "USD")
    if fx.empty:
        st.info("FX data unavailable.")
    else:
        avail = [c for c in cur if c in fx.index]
        x1, x2, x3 = st.columns(3)
        amt = x1.number_input("Amount", value=100.0, min_value=0.0)
        fr = x2.selectbox("From", avail, index=0)
        to = x3.selectbox("To", avail, index=avail.index("EUR") if "EUR" in avail else 1)
        st.success(f"{amt:,.2f} {fr} = **{amt * fx[to] / fx[fr]:,.2f} {to}**")
        m = pd.DataFrame([[fx[j] / fx[i] for j in avail[:12]] for i in avail[:12]], index=avail[:12], columns=avail[:12])
        fig = px.imshow(np.log10(m.astype(float)), x=list(m.columns), y=list(m.index), color_continuous_scale="RdBu_r", aspect="auto")
        fig.update_traces(text=m.round(3).values, texttemplate="%{text}", hovertemplate="1 %{y} = %{text} %{x}<extra></extra>")
        clean_layout(fig, 520).update_layout(coloraxis_showscale=False, title="Cross-rates: 1 [row] = x [column]")
        plot(fig)


def page_weather():
    region = st.session_state.get("region", "World")
    hero("🌦️ Weather & Air Quality", "Live conditions for 55 world cities, regional maps, rankings and a 7-day forecast for any city")
    cdf = pd.DataFrame(CITIES, columns=["city", "country", "continent", "lat", "lon"])
    wx = safe(load_multi_weather, pd.DataFrame(), tuple(cdf["lat"]), tuple(cdf["lon"]))
    aq = safe(load_multi_aqi, pd.DataFrame(), tuple(cdf["lat"]), tuple(cdf["lon"]))
    if not wx.empty and len(wx) == len(cdf):
        df = pd.concat([cdf, wx], axis=1)
        if not aq.empty and len(aq) == len(cdf):
            df = pd.concat([df, aq], axis=1)
        layers = {"Temperature (°C)": ("temp", "RdYlBu_r"), "Feels like (°C)": ("feels", "RdYlBu_r"), "Humidity (%)": ("humidity", "Blues"),
                  "Wind (km/h)": ("wind", "Viridis"), "Rain now (mm)": ("precip", "Blues"), "Pressure (hPa)": ("pressure", "Viridis")}
        if "aqi" in df:
            layers["Air quality (US AQI)"] = ("aqi", "YlOrRd")
        lab = st.selectbox("Map layer", list(layers))
        col, scale = layers[lab]
        d = in_region(df, region).dropna(subset=[col])
        fig = px.scatter_geo(d, lat="lat", lon="lon", color=col, hover_name="city",
                             hover_data={"country": True, "conditions": True, "temp": True, "wind": True, "lat": False, "lon": False},
                             color_continuous_scale=scale, text="city" if region != "World" else None)
        fig.update_traces(marker=dict(size=15, line=dict(width=1, color="white")), textposition="top center")
        fig.update_coloraxes(colorbar=dict(title=None, thickness=10, len=0.55))
        plot(style_geo(fig, region, 560))
        k = st.columns(4)
        hot, cold, wind = df.loc[df["temp"].idxmax()], df.loc[df["temp"].idxmin()], df.loc[df["wind"].idxmax()]
        kpi(k[0], "Hottest now", hot["city"], f"{hot['temp']:.1f}°C", "down")
        kpi(k[1], "Coldest now", cold["city"], f"{cold['temp']:.1f}°C", "up")
        kpi(k[2], "Windiest", wind["city"], f"{wind['wind']:.0f} km/h")
        if "aqi" in df and df["aqi"].notna().any():
            pol = df.loc[df["aqi"].idxmax()]
            kpi(k[3], "Most polluted air", pol["city"], f"AQI {pol['aqi']:.0f} · {aqi_label(pol['aqi'])}", "down")
        a, b = st.columns(2)
        with a:
            fig = px.bar(df.sort_values("temp"), x="temp", y="city", orientation="h", color="continent", height=900)
            clean_layout(fig, 900).update_layout(title="Temperature ranking (°C)", yaxis_title="", xaxis_title="")
            plot(fig)
        with b:
            fig = px.box(df, x="continent", y="temp", color="continent", points="all", hover_name="city")
            clean_layout(fig, 420).update_layout(showlegend=False, title="Temperature by continent", xaxis_title="", yaxis_title="°C")
            plot(fig)
            fig = px.scatter(df, x="temp", y="humidity", color="continent", hover_name="city", size="wind")
            clean_layout(fig, 420).update_layout(title="Temperature vs humidity (size = wind)")
            plot(fig)
    else:
        st.warning("World weather unavailable right now.")

    st.subheader("🔎 Forecast for any city")
    q = st.text_input("Search a city anywhere", "London")
    res = safe(geocode, [], q) if q else []
    if res:
        opt = {f"{r['name']}, {r.get('admin1', '')}, {r.get('country', '')}".replace(", ,", ","): r for r in res}
        r = opt[st.selectbox("Match", list(opt))]
        forecast_panel(r["latitude"], r["longitude"])
    elif q:
        st.info("City not found.")


def page_hazards():
    region = st.session_state.get("region", "World")
    hero("🌋 Earth & Hazards", "Earthquakes, volcanoes, wildfires, storms, floods and global disaster alerts")
    feeds = {"Past hour (all)": "all_hour", "Past day (M2.5+)": "2.5_day", "Past week (M2.5+)": "2.5_week",
             "Past week (M4.5+)": "4.5_week", "Past month (M4.5+)": "4.5_month", "Significant — past month": "significant_month"}
    c1, c2, c3 = st.columns([2, 2, 3])
    fk = c1.selectbox("Earthquake window", list(feeds), index=1)
    q = safe(load_quakes, pd.DataFrame(), feeds[fk])
    ev = safe(load_eonet, pd.DataFrame())
    gd = safe(load_gdacs, pd.DataFrame())
    minmag = c2.slider("Minimum magnitude", 0.0, 8.0, 2.5, 0.1)
    layers = c3.multiselect("Map layers", ["Earthquakes", "Natural events (NASA)", "Disaster alerts (GDACS)"], default=["Earthquakes", "Natural events (NASA)", "Disaster alerts (GDACS)"])
    qf = q[q["magnitude"] >= minmag] if not q.empty else q
    plot(hazard_map(qf, ev, gd, region, 600, tuple(layers)))
    if not qf.empty:
        qr = in_region(qf, region)
        k = st.columns(4)
        kpi(k[0], f"Quakes in {region}", len(qr), f"{len(qf)} worldwide")
        kpi(k[1], "Strongest", f"M{qr['magnitude'].max():.1f}" if not qr.empty else "—", qr.loc[qr['magnitude'].idxmax(), 'place'] if not qr.empty else "")
        kpi(k[2], "Median depth", f"{qr['depth_km'].median():.0f} km" if not qr.empty else "—")
        kpi(k[3], "Tsunami flags", int(qr["tsunami"].sum()) if not qr.empty else 0)
        a, b = st.columns(2)
        with a:
            fig = px.histogram(qr, x="magnitude", nbins=25, color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 300).update_layout(title="Magnitude distribution", yaxis_title="quakes")
            plot(fig)
            daily = qr.assign(day=qr["time"].dt.floor("D")).groupby("day").size().reset_index(name="quakes")
            fig = px.bar(daily, x="day", y="quakes", color_discrete_sequence=["#f59e0b"])
            clean_layout(fig, 300).update_layout(title="Quakes per day", xaxis_title="")
            plot(fig)
        with b:
            fig = px.scatter(qr, x="magnitude", y="depth_km", color="magnitude", color_continuous_scale="YlOrRd", hover_name="place")
            fig.update_yaxes(autorange="reversed")
            clean_layout(fig, 300).update_layout(title="Depth vs magnitude", coloraxis_showscale=False, yaxis_title="depth (km)")
            plot(fig)
            top = qr.nlargest(10, "magnitude")[["time", "magnitude", "place", "depth_km", "url"]].copy()
            top["time"] = top["time"].dt.strftime("%d %b %H:%M UTC")
            table(top, column_config={"url": st.column_config.LinkColumn("Details", display_text="open")})
    st.subheader("🔥 Natural events & alerts")
    a, b = st.columns(2)
    with a:
        if not ev.empty:
            e = in_region(ev, region)
            cnt = e["category"].value_counts().reset_index()
            cnt.columns = ["category", "events"]
            fig = px.bar(cnt, x="events", y="category", orientation="h", color="category")
            clean_layout(fig, 320).update_layout(showlegend=False, yaxis_title="", title=f"Open NASA EONET events — {region}")
            plot(fig)
            table(e[["event", "category", "date", "link"]].sort_values("date", ascending=False),
                  column_config={"link": st.column_config.LinkColumn("Source", display_text="open")})
    with b:
        if not gd.empty:
            fig = px.histogram(gd, x="type", color="alert", color_discrete_map={"Green": "#22c55e", "Orange": "#f97316", "Red": "#ef4444"})
            clean_layout(fig, 320).update_layout(title="GDACS alerts by type", xaxis_title="")
            plot(fig)
            table(gd[["alert", "type", "country", "title", "link"]], column_config={"link": st.column_config.LinkColumn("Link", display_text="open")})


@st.fragment(run_every="15s")
def iss_panel():
    iss = safe(load_iss, None)
    trk = safe(load_iss_track, pd.DataFrame(), int(time.time() // 60) * 60)
    if not iss:
        st.warning("ISS position unavailable.")
        return
    fig = go.Figure()
    if not trk.empty:
        lats, lons = [], []
        for i, r in enumerate(trk.itertuples()):
            if i and abs(r.lon - trk.iloc[i - 1]["lon"]) > 180:
                lats.append(None)
                lons.append(None)
            lats.append(r.lat)
            lons.append(r.lon)
        fig.add_trace(go.Scattergeo(lat=lats, lon=lons, mode="lines", line=dict(width=2, color="#f59e0b", dash="dot"), name="Ground track (−40 / +50 min)"))
    fig.add_trace(go.Scattergeo(lat=[iss["latitude"]], lon=[iss["longitude"]], mode="markers+text", text=["ISS"], textposition="top center",
                                marker=dict(size=14, color="#ef4444", symbol="diamond", line=dict(width=1.5, color="white")), name="ISS now"))
    plot(style_geo(fig, "World", 420))
    k = st.columns(4)
    kpi(k[0], "Altitude", f"{iss['altitude']:.0f} km")
    kpi(k[1], "Speed", f"{iss['velocity']:,.0f} km/h")
    kpi(k[2], "Position", f"{iss['latitude']:.1f}°, {iss['longitude']:.1f}°")
    kpi(k[3], "Sunlight", str(iss.get("visibility", "—")).title())
    st.caption("Updates every 15 seconds.")


def page_space():
    hero("🚀 Space & Sky", "ISS live tracker, crew, launches, asteroids, space weather and NASA's picture of the day")
    t1, t2, t3, t4 = st.tabs(["🛰️ ISS live", "🚀 Launches & asteroids", "☀️ Space weather", "🌌 Picture of the day"])
    with t1:
        l, r = st.columns([3, 1])
        with l:
            iss_panel()
        with r:
            st.subheader("People in space")
            ppl = safe(load_astronauts, pd.DataFrame())
            if ppl.empty:
                st.info("Crew data unavailable.")
            else:
                kpi(st, "Total in orbit", len(ppl))
                table(ppl)
    with t2:
        st.subheader("Upcoming launches")
        la = safe(load_launches, pd.DataFrame())
        if la.empty:
            st.info("Launch schedule unavailable (free API is rate-limited).")
        else:
            la["when"] = pd.to_datetime(la["when"], errors="coerce").dt.strftime("%d %b %Y %H:%M UTC")
            table(la)
        st.subheader("Near-Earth asteroids passing today")
        neo = safe(load_neo, pd.DataFrame())
        if neo.empty:
            st.info("Asteroid feed unavailable (NASA demo key is rate-limited).")
        else:
            fig = px.scatter(neo, x="miss_lunar", y="diameter_m", size="speed_kmh", color="hazardous", hover_name="object",
                             color_discrete_map={True: "#ef4444", False: "#3b82f6"}, log_x=True, log_y=True)
            clean_layout(fig, 360).update_layout(xaxis_title="Miss distance (× Moon distance)", yaxis_title="Max diameter (m)")
            plot(fig)
            table(neo)
    with t3:
        kp = safe(load_kp, pd.DataFrame())
        if kp.empty:
            st.info("NOAA space-weather data unavailable.")
        else:
            now_kp = kp["kp"].iloc[-1]
            k = st.columns(3)
            kpi(k[0], "Planetary Kp index", f"{now_kp:.1f}", "Storm (≥5)" if now_kp >= 5 else "Quiet to unsettled", "down" if now_kp >= 5 else "up")
            kpi(k[1], "7-day max Kp", f"{kp['kp'].max():.1f}")
            fig = px.bar(kp, x="time_tag", y="kp", color="kp", color_continuous_scale="RdYlGn_r", range_color=(0, 9))
            clean_layout(fig, 300).update_layout(coloraxis_showscale=False, xaxis_title="", title="Geomagnetic activity (Kp, 3-hourly)")
            plot(fig)
        al = safe(load_swpc_alerts, pd.DataFrame())
        if not al.empty:
            st.subheader("NOAA SWPC alerts")
            for r in al.itertuples():
                with st.expander(f"{getattr(r, 'issue_datetime', '')} — {str(getattr(r, 'message', ''))[:70].strip()}"):
                    st.text(getattr(r, "message", ""))
    with t4:
        ap = safe(load_apod, None)
        if ap:
            st.markdown(f"### {ap.get('title', '')}  \n<span class='src-tag'>{ap.get('date', '')}</span>", unsafe_allow_html=True)
            if ap.get("media_type") == "image":
                img(ap.get("url"))
            elif ap.get("url"):
                embed(ap["url"], 420)
            st.write(ap.get("explanation", ""))
        else:
            st.info("APOD unavailable (NASA demo key rate-limited).")


def page_cams():
    hero("📹 Live Cams & Imagery", "Live news streams, satellite views of Earth, the Sun right now, and optional webcam snapshots near any city")
    t1, t2, t3 = st.tabs(["📺 Live news streams", "🛰️ Satellite & Sun", "📷 City webcams"])
    with t1:
        pick = st.multiselect("Choose up to 4 streams", list(LIVE_CHANNELS), default=["Al Jazeera English", "Sky News"], max_selections=4)
        cols = st.columns(2)
        for i, nme in enumerate(pick):
            with cols[i % 2]:
                st.markdown(f"**{nme}**")
                embed(f"https://www.youtube.com/embed/live_stream?channel={LIVE_CHANNELS[nme]}", 330)
        st.markdown("**Paste any YouTube link** (live stream or video)")
        url = st.text_input("YouTube URL", "", label_visibility="collapsed", placeholder="https://www.youtube.com/watch?v=…")
        m = re.search(r"(?:v=|youtu\.be/|/live/|/embed/)([\w-]{11})", url or "")
        if m:
            embed(f"https://www.youtube.com/embed/{m.group(1)}", 420)
        st.caption("Streams are provided by the broadcasters via YouTube; availability depends on each channel being live and allowing embedding in your country.")
    with t2:
        stamp = int(time.time() // 300)
        cols = st.columns(2)
        for i, (nme, u) in enumerate(IMAGERY.items()):
            with cols[i % 2]:
                st.markdown(f"**{nme}**")
                img(f"{u}?t={stamp}")
        st.caption("Latest captures from NOAA GOES satellites and NASA's Solar Dynamics Observatory; images refresh every few minutes at the source.")
    with t3:
        key = get_secret("WINDY_KEY")
        if not key:
            st.info("Real city webcams need a free API key from api.windy.com/webcams. "
                    "Add it in Streamlit Cloud → App settings → Secrets as:\n\n`WINDY_KEY = \"your-key\"`\n\nThen search a city here to see recent snapshots from webcams within 150 km.")
        else:
            q = st.text_input("City", "Tokyo")
            res = safe(geocode, [], q) if q else []
            if res:
                r0 = res[0]
                cams = safe(load_windy, [], r0["latitude"], r0["longitude"], key)
                if not cams:
                    st.info("No webcams returned.")
                cols = st.columns(3)
                for i, c in enumerate(cams):
                    with cols[i % 3]:
                        im = ((c.get("images") or {}).get("current") or {}).get("preview")
                        if im:
                            img(im)
                        loc = c.get("location") or {}
                        det = (c.get("urls") or {}).get("detail")
                        st.markdown(f"[{esc(c.get('title', 'Webcam'))}]({det})" if det else esc(c.get("title", "Webcam")))
                        st.caption(f"{loc.get('city', '')}, {loc.get('country', '')}")


def page_trending():
    hero("🔥 Trending Now", "What the world is reading, searching and discussing")
    a, b = st.columns(2)
    with a:
        st.subheader("📚 Most-read on Wikipedia")
        res = safe(load_wikipedia_top, (pd.DataFrame(), ""))
        wk, day = res
        if wk.empty:
            st.info("Wikipedia trends unavailable.")
        else:
            st.caption(f"English Wikipedia · {day}")
            fig = px.bar(wk.head(15).iloc[::-1], x="views", y="article", orientation="h", color_discrete_sequence=["#3b82f6"])
            clean_layout(fig, 520).update_layout(yaxis_title="")
            plot(fig)
    with b:
        st.subheader("🔍 Google Trends (daily searches)")
        geos = {"United States": "US", "United Kingdom": "GB", "India": "IN", "Malaysia": "MY", "Singapore": "SG", "Australia": "AU",
                "Canada": "CA", "Germany": "DE", "France": "FR", "Japan": "JP", "Brazil": "BR", "Nigeria": "NG", "South Africa": "ZA", "Indonesia": "ID"}
        g = st.selectbox("Country", list(geos))
        tr = safe(load_gtrends, pd.DataFrame(), geos[g])
        if tr.empty:
            st.info("Trends feed unavailable.")
        else:
            table(tr, column_config={"link": st.column_config.LinkColumn("Search", display_text="open")})
    st.subheader("💻 Hacker News front page")
    hn = safe(load_hn, pd.DataFrame())
    if hn.empty:
        st.info("Hacker News unavailable.")
    else:
        for r in hn.itertuples():
            st.markdown(f"**[{esc(r.title)}]({r.url})**  \n<span class='src-tag'>▲ {r.points} · 💬 {r.comments}</span>", unsafe_allow_html=True)


def page_status():
    hero("🩺 Source Status", "Live connectivity check for every data source used by this dashboard")
    probes = {
        "REST Countries": "https://restcountries.com/v3.1/alpha/MYS", "World Bank": "https://api.worldbank.org/v2/country/MYS?format=json",
        "disease.sh (COVID)": "https://disease.sh/v3/covid-19/all", "WHO Outbreak News": "https://www.who.int/feeds/entity/csr/don/en/rss.xml",
        "CDC Travel Notices": "https://wwwnc.cdc.gov/travel/rss/notices.xml", "Google News RSS": "https://news.google.com/rss?hl=en&gl=US&ceid=US:en",
        "BBC RSS": NEWS_FEEDS["World"]["BBC"], "Al Jazeera RSS": NEWS_FEEDS["World"]["Al Jazeera"],
        "USGS Earthquakes": "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson", "NASA EONET": "https://eonet.gsfc.nasa.gov/api/v3/events?limit=1",
        "GDACS": "https://www.gdacs.org/xml/rss.xml", "Open-Meteo": "https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&current=temperature_2m",
        "Open-Meteo Air Quality": "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=0&longitude=0&current=us_aqi",
        "Wikidata SPARQL": "https://query.wikidata.org/sparql?query=ASK%7B%7D&format=json", "CoinGecko": "https://api.coingecko.com/api/v3/ping",
        "FX rates": "https://open.er-api.com/v6/latest/USD", "ISS (wheretheiss.at)": "https://api.wheretheiss.at/v1/satellites/25544",
        "Open Notify (crew)": "http://api.open-notify.org/astros.json", "NASA APOD": "https://api.nasa.gov/planetary/apod?api_key=DEMO_KEY",
        "Launch Library 2": "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=1", "NOAA SWPC": "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json",
        "Wikimedia": "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/2024/01/01", "Hacker News": "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=1",
        "Google Trends RSS": "https://trends.google.com/trending/rss?geo=US", "NOAA GOES imagery": IMAGERY["GOES-East (Americas) — full disk"],
    }

    def ping(kv):
        t = time.time()
        try:
            r = requests.get(kv[1], headers=HEADERS, timeout=10, stream=True)
            return dict(source=kv[0], status="✅ OK" if r.status_code < 400 else f"⚠️ HTTP {r.status_code}", ms=int((time.time() - t) * 1000))
        except Exception as e:  # noqa: BLE001
            return dict(source=kv[0], status=f"❌ {type(e).__name__}", ms=None)
    if st.button("Run connectivity check"):
        with ThreadPoolExecutor(10) as ex:
            res = pd.DataFrame(list(ex.map(ping, probes.items())))
        k = st.columns(3)
        kpi(k[0], "Sources reachable", f"{res['status'].str.startswith('✅').sum()} / {len(res)}")
        table(res)
    else:
        st.info("Click the button to test every source from the server that is running this app.")
    st.caption("Yahoo Finance (yfinance) is tested on the Markets page. Sources that fail here are skipped gracefully elsewhere.")


def safe(fn, default, *args, **kwargs):
    """Run a loader; on failure record the REAL error and skip retries for 90 s."""
    key = f"{fn.__name__}:{hash((args, tuple(sorted(kwargs.items()))))}"
    fails = st.session_state.setdefault("_fails", {})
    f = fails.get(key)
    if f and (datetime.now() - f[0]).total_seconds() < 90:
        ERRORS.append(f"{fn.__name__}: skipped — last error: {f[1]}")
        return default
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {str(e)[:110]}"
        fails[key] = (datetime.now(), msg)
        ERRORS.append(f"{fn.__name__}: {msg}")
        return default


def _rc_fetch():
    last = None
    for i in range(3):  # retry with backoff
        try:
            return get_json("https://restcountries.com/v3.1/all",
                            {"fields": "name,cca2,cca3,continents,subregion,population,area,capital,latlng,flags"}, timeout=30)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


_WB_CONT = {"East Asia & Pacific": "Asia", "Europe & Central Asia": "Europe", "Latin America & Caribbean": "South America",
            "Middle East & North Africa": "Africa", "North America": "North America", "South Asia": "Asia",
            "Sub-Saharan Africa": "Africa"}


def _countries_from_worldbank():
    """Fallback when restcountries.com is blocked/down: World Bank metadata + flagcdn flags."""
    rows = get_json("https://api.worldbank.org/v2/country", {"format": "json", "per_page": 400}, timeout=30)[1]
    pop, area = _wb_latest("SP.POP.TOTL"), _wb_latest("AG.SRF.TOTL.K2")
    out = []
    for r in rows:
        reg = (r.get("region") or {}).get("value", "")
        if reg in ("Aggregates", ""):
            continue
        try:
            lat, lon = float(r["latitude"]), float(r["longitude"])
        except (ValueError, TypeError, KeyError):
            lat = lon = None
        i3, i2 = r["id"], r.get("iso2Code", "")
        cont = "Asia" if i3 in ("SAU", "ARE", "IRN", "IRQ", "ISR", "JOR", "KWT", "LBN", "OMN", "QAT", "SYR", "YEM", "BHR", "TUR") else _WB_CONT.get(reg, "Other")
        out.append(dict(country=r["name"], official=r["name"], iso2=i2, iso3=i3, continent=cont, subregion=reg,
                        population=pop.get(i3), area=area.get(i3), capital=r.get("capitalCity") or None, lat=lat, lon=lon,
                        flag=f"https://flagcdn.com/w160/{i2.lower()}.png" if i2 else None))
    return pd.DataFrame(out)


@st.cache_data(ttl=86400, show_spinner=False)
def load_countries():
    try:
        rows = []
        for c in _rc_fetch():
            ll = c.get("latlng") or [None, None]
            rows.append(dict(country=c["name"]["common"], official=c["name"].get("official"), iso2=c.get("cca2"), iso3=c.get("cca3"),
                             continent=(c.get("continents") or ["Other"])[0], subregion=c.get("subregion") or "Other",
                             population=c.get("population"), area=c.get("area"), capital=(c.get("capital") or [None])[0],
                             lat=ll[0], lon=ll[1], flag=(c.get("flags") or {}).get("png")))
        df = pd.DataFrame(rows)
    except Exception:  # noqa: BLE001
        df = _countries_from_worldbank()  # raises if this fails too, so the real error is shown
    df["density"] = df["population"] / df["area"].replace(0, np.nan)
    return df.sort_values("country").reset_index(drop=True)



@st.cache_data(ttl=86400, show_spinner=False)
def load_passports():
    url = "https://raw.githubusercontent.com/ilyankou/passport-index-dataset/master/passport-index-tidy-iso3.csv"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = [c.strip().title() for c in df.columns]

    def cls(x):
        x = str(x).strip().lower()
        if x == "-1":
            return "self"
        if x in ("visa free",) or x.isdigit():
            return "visa_free"
        return {"visa on arrival": "voa", "eta": "eta", "e-visa": "evisa", "visa required": "visa",
                "no admission": "banned"}.get(x, "visa")
    df["cat"] = df["Requirement"].map(cls)
    return df[df["cat"] != "self"]


def page_passports():
    hero("🛂 Passport Power", "Visa-free access ranking, world map and visa checker for every passport")
    m = safe(load_passports, pd.DataFrame())
    if m.empty:
        st.error("Passport dataset unavailable (GitHub raw). Try Refresh.")
        return
    wt = world_table()
    nm = dict(zip(wt["iso3"], wt["country"])) if not wt.empty else {}
    cnt = m.pivot_table(index="Passport", columns="cat", values="Destination", aggfunc="count", fill_value=0)
    for c in ("visa_free", "voa", "eta", "evisa", "visa", "banned"):
        if c not in cnt:
            cnt[c] = 0
    cnt["score"] = cnt["visa_free"] + cnt["voa"] + cnt["eta"]
    cnt = cnt.sort_values("score", ascending=False)
    cnt["rank"] = cnt["score"].rank(method="min", ascending=False).astype(int)
    cnt["country"] = [nm.get(i, i) for i in cnt.index]
    k = st.columns(3)
    kpi(k[0], "Most powerful", cnt["country"].iloc[0], f"{int(cnt['score'].iloc[0])} destinations")
    kpi(k[1], "Median passport", f"{int(cnt['score'].median())}", "destinations without prior visa")
    kpi(k[2], "Weakest", cnt["country"].iloc[-1], f"{int(cnt['score'].iloc[-1])} destinations", "down")
    st.caption("Score = visa-free + visa-on-arrival + eTA destinations. Community dataset (passport-index), not the official Henley index; "
               "it can differ by a few places and lags real-world changes.")
    if not wt.empty:
        d = wt.merge(cnt.reset_index().rename(columns={"Passport": "iso3"})[["iso3", "score"]], on="iso3")
        plot(choropleth_map(d, "score", st.session_state.get("region", "World"), "Viridis", 520))
    l, r = st.columns([3, 2])
    with l:
        table(cnt.reset_index(drop=True)[["rank", "country", "visa_free", "voa", "eta", "evisa", "visa", "score"]].rename(
            columns={"visa_free": "Visa-free", "voa": "On arrival", "eta": "eTA", "evisa": "e-Visa", "visa": "Visa required", "score": "Access score"}))
    with r:
        top = cnt.head(15).iloc[::-1]
        fig = px.bar(top, x=["visa_free", "voa", "eta"], y="country", orientation="h")
        clean_layout(fig, 520).update_layout(title="Top 15 passports", yaxis_title="", xaxis_title="destinations", legend_title="")
        plot(fig)
    st.subheader("🔍 Visa checker")
    names = sorted(set(nm.get(i, i) for i in m["Passport"].unique()))
    inv = {v: k for k, v in nm.items()}
    a, b = st.columns(2)
    p = a.selectbox("My passport", names, index=names.index("Malaysia") if "Malaysia" in names else 0)
    t = b.selectbox("Destination", names, index=names.index("Japan") if "Japan" in names else 1)
    row = m[(m["Passport"] == inv.get(p, p)) & (m["Destination"] == inv.get(t, t))]
    if row.empty:
        st.info("No data for that pair.")
    else:
        st.success(f"{p} → {t}: **{row['Requirement'].iloc[0]}**")
    st.caption("Always confirm with the destination's embassy before travelling.")


@st.cache_data(ttl=86400, show_spinner=False)
def load_co2():
    t = requests.get("https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.csv", headers=HEADERS, timeout=30).text
    df = pd.read_csv(io.StringIO(t), comment="#", header=None).apply(pd.to_numeric, errors="coerce").dropna(subset=[0, 1, 3])
    df = df[df[3] > 0]
    return pd.DataFrame({"date": pd.to_datetime(dict(year=df[0].astype(int), month=df[1].astype(int), day=1)), "ppm": df[3].values})


@st.cache_data(ttl=86400, show_spinner=False)
def load_temp_anomaly():
    t = requests.get("https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts+dSST.csv", headers=HEADERS, timeout=30).text
    df = pd.read_csv(io.StringIO(t), skiprows=1, na_values="***")
    df["J-D"] = pd.to_numeric(df["J-D"], errors="coerce")
    return df[["Year", "J-D"]].dropna().rename(columns={"J-D": "anomaly"})


def page_climate():
    hero("🌡️ Climate Watch", "Atmospheric CO₂ at Mauna Loa and global temperature anomaly since 1880")
    co2, ta = safe(load_co2, pd.DataFrame()), safe(load_temp_anomaly, pd.DataFrame())
    k = st.columns(3)
    if not co2.empty:
        kpi(k[0], "CO₂ (latest month)", f"{co2['ppm'].iloc[-1]:.1f} ppm", f"{co2['ppm'].iloc[-1] - co2['ppm'].iloc[-13]:+.1f} ppm vs 1 yr ago", "down")
    if not ta.empty:
        kpi(k[1], "Latest annual anomaly", f"{ta['anomaly'].iloc[-1]:+.2f} °C", f"vs 1951–1980 · {int(ta['Year'].iloc[-1])}", "down")
        kpi(k[2], "Warmest year on record", str(int(ta.loc[ta['anomaly'].idxmax(), 'Year'])), f"{ta['anomaly'].max():+.2f} °C")
    a, b = st.columns(2)
    with a:
        if co2.empty:
            st.info("CO₂ data unavailable.")
        else:
            fig = px.line(co2, x="date", y="ppm", color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 360).update_layout(title="Mauna Loa monthly CO₂ (ppm)", xaxis_title="", yaxis_title="")
            plot(fig)
    with b:
        if ta.empty:
            st.info("Temperature data unavailable.")
        else:
            fig = px.bar(ta, x="Year", y="anomaly", color="anomaly", color_continuous_scale="RdBu_r", color_continuous_midpoint=0)
            clean_layout(fig, 360).update_layout(title="Global temperature anomaly (°C, NASA GISS)", coloraxis_showscale=False, yaxis_title="")
            plot(fig)


@st.cache_data(ttl=60, show_spinner=False)
def load_flights():
    d = get_json("https://opensky-network.org/api/states/all", timeout=25).get("states") or []
    df = pd.DataFrame([dict(callsign=(s[1] or "").strip(), origin=s[2], lon=s[5], lat=s[6], alt_m=s[7], speed_kmh=(s[9] or 0) * 3.6, on_ground=s[8])
                       for s in d if s[5] is not None and s[6] is not None])
    return df


def page_aviation():
    region = st.session_state.get("region", "World")
    hero("✈️ Live Flights", "Aircraft currently broadcasting ADS-B (OpenSky, anonymous tier — rate-limited)")
    df = safe(load_flights, pd.DataFrame())
    if df.empty:
        st.info("OpenSky unavailable or rate-limited. Wait a minute and refresh.")
        return
    air = in_region(df[~df["on_ground"]], region)
    k = st.columns(3)
    kpi(k[0], f"Airborne in {region}", fnum(len(air), 0), f"{fnum(len(df), 0)} tracked worldwide")
    kpi(k[1], "Avg cruising altitude", f"{air['alt_m'].mean() * 3.28084:,.0f} ft" if not air.empty else "—")
    kpi(k[2], "Avg speed", f"{air['speed_kmh'].mean():,.0f} km/h" if not air.empty else "—")
    s = air.sample(min(len(air), 4000), random_state=1) if not air.empty else air
    fig = go.Figure(go.Scattergeo(lat=s["lat"], lon=s["lon"], mode="markers", text=s["callsign"] + " · " + s["origin"], hoverinfo="text",
                                  marker=dict(size=3, color=s["alt_m"], colorscale="Turbo", showscale=True, colorbar=dict(title="m", thickness=10, len=.5))))
    plot(style_geo(fig, region, 560))
    top = air["origin"].value_counts().head(12).reset_index()
    top.columns = ["country", "aircraft"]
    fig = px.bar(top.iloc[::-1], x="aircraft", y="country", orientation="h")
    clean_layout(fig, 360).update_layout(title="Aircraft by registration country", yaxis_title="")
    plot(fig)


@st.cache_data(ttl=3600, show_spinner=False)
def load_kev():
    v = get_json("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json", timeout=40)["vulnerabilities"]
    df = pd.DataFrame(v)
    df["dateAdded"] = pd.to_datetime(df["dateAdded"])
    return df.sort_values("dateAdded", ascending=False).reset_index(drop=True)


STATUS_PAGES = {"GitHub": "githubstatus.com", "Cloudflare": "cloudflarestatus.com", "Discord": "discordstatus.com",
                "OpenAI": "status.openai.com", "Anthropic": "status.anthropic.com", "Atlassian": "status.atlassian.com",
                "Slack": "slack-status.com", "Zoom": "status.zoom.us", "Dropbox": "status.dropbox.com", "Reddit": "redditstatus.com"}


@st.cache_data(ttl=300, show_spinner=False)
def load_status_pages():
    def one(kv):
        try:
            d = get_json(f"https://{kv[1]}/api/v2/status.json", timeout=8)
            return dict(service=kv[0], state=d["status"]["description"], level=d["status"]["indicator"])
        except Exception:  # noqa: BLE001
            return dict(service=kv[0], state="unreachable / no public API", level="unknown")
    with ThreadPoolExecutor(10) as ex:
        return pd.DataFrame(list(ex.map(one, STATUS_PAGES.items())))


def page_cyber():
    hero("🛡️ Cyber & Internet Health", "CISA actively-exploited vulnerabilities and status of major online services")
    kev = safe(load_kev, pd.DataFrame())
    if not kev.empty:
        k = st.columns(3)
        kpi(k[0], "Known exploited CVEs", fnum(len(kev), 0), "CISA KEV catalog")
        kpi(k[1], "Added last 30 days", int((kev["dateAdded"] > pd.Timestamp.now() - pd.Timedelta(days=30)).sum()))
        kpi(k[2], "Ransomware-linked", int((kev["knownRansomwareCampaignUse"] == "Known").sum()), "", "down")
        a, b = st.columns([3, 2])
        with a:
            table(kev.head(25)[["dateAdded", "cveID", "vendorProject", "product", "vulnerabilityName"]])
        with b:
            v = kev["vendorProject"].value_counts().head(12).reset_index()
            v.columns = ["vendor", "CVEs"]
            fig = px.bar(v.iloc[::-1], x="CVEs", y="vendor", orientation="h", color_discrete_sequence=["#ef4444"])
            clean_layout(fig, 520).update_layout(title="Most-exploited vendors", yaxis_title="")
            plot(fig)
    else:
        st.info("CISA feed unavailable.")
    st.subheader("Service status")
    stp = safe(load_status_pages, pd.DataFrame())
    if not stp.empty:
        table(stp)


@st.cache_data(ttl=3600, show_spinner=False)
def load_holidays(iso2, year):
    return pd.DataFrame(get_json(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{iso2}"))[["date", "localName", "name"]]


@st.cache_data(ttl=3600, show_spinner=False)
def load_onthisday():
    n = datetime.now(timezone.utc)
    ev = get_json(f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{n:%m}/{n:%d}")["events"]
    return pd.DataFrame([dict(year=e["year"], event=e["text"]) for e in ev]).sort_values("year", ascending=False)


@st.cache_data(ttl=3600, show_spinner=False)
def load_fng():
    d = get_json("https://api.alternative.me/fng/", {"limit": 60})["data"]
    return pd.DataFrame([dict(date=pd.to_datetime(int(x["timestamp"]), unit="s"), value=int(x["value"]), label=x["value_classification"]) for x in d])


def page_calendar():
    hero("📅 Calendar & Society", "Public holidays by country, this day in history, and crypto market sentiment")
    wt = world_table()
    if not wt.empty:
        names = wt["country"].tolist()
        c = st.selectbox("Country", names, index=names.index("Malaysia") if "Malaysia" in names else 0)
        yr = datetime.now().year
        h = safe(load_holidays, pd.DataFrame(), wt.loc[wt["country"] == c, "iso2"].iloc[0], yr)
        table(h) if not h.empty else st.info("No holiday data for this country.")
    a, b = st.columns(2)
    with a:
        st.subheader("📜 On this day")
        oh = safe(load_onthisday, pd.DataFrame())
        for r in oh.head(12).itertuples():
            st.markdown(f"**{r.year}** — {esc(r.event)}")
    with b:
        st.subheader("😱 Crypto Fear & Greed")
        fg = safe(load_fng, pd.DataFrame())
        if not fg.empty:
            kpi(st, "Today", str(fg["value"].iloc[0]), fg["label"].iloc[0])
            fig = px.area(fg.iloc[::-1], x="date", y="value", color_discrete_sequence=["#f59e0b"])
            clean_layout(fig, 300).update_layout(yaxis_range=[0, 100], xaxis_title="", yaxis_title="")
            plot(fig)



_DL_N = [0]


def table(df, **kw):
    """st.dataframe + automatic CSV download button for tables over 5 rows."""
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kw)
    except Exception:  # noqa: BLE001
        st.dataframe(df, hide_index=True, use_container_width=True, **kw)
    if df is not None and len(df) > 5:
        _DL_N[0] += 1
        st.download_button("⬇ CSV", df.to_csv(index=False).encode(), f"worldmonitor_{_DL_N[0]}.csv", "text/csv", key=f"dl{_DL_N[0]}")


def ticker():
    """Scrolling headline bar shown above every page."""
    n = safe(load_news, pd.DataFrame(), "World", ("BBC", "Al Jazeera", "NPR"))
    if n.empty:
        return
    t = "  ●  ".join(html.escape(x) for x in n["title"].head(14))
    st.markdown("<div style='overflow:hidden;white-space:nowrap;border-radius:10px;padding:6px 0;background:rgba(128,128,128,.12);font-size:.85rem'>"
                f"<div style='display:inline-block;padding-left:100%;animation:tk 160s linear infinite'>{t}</div></div>"
                "<style>@keyframes tk{to{transform:translateX(-100%)}}</style>", unsafe_allow_html=True)


def _get_text(url, params=None, timeout=30):
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text



# ---- Markets+ : yield curve, sectors, Big Mac, DeFi -------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_yields():
    y = datetime.now().year
    t = _get_text("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
                  f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
    df = pd.read_csv(io.StringIO(t))
    df["Date"] = pd.to_datetime(df["Date"])
    return df.sort_values("Date").reset_index(drop=True)


@st.cache_data(ttl=86400, show_spinner=False)
def load_bigmac():
    df = pd.read_csv(io.StringIO(_get_text("https://raw.githubusercontent.com/TheEconomist/big-mac-data/master/output-data/big-mac-full-index.csv")))
    df["date"] = pd.to_datetime(df["date"])
    return df[df["date"] == df["date"].max()].copy()


@st.cache_data(ttl=1800, show_spinner=False)
def load_defi():
    return pd.DataFrame(get_json("https://api.llama.fi/v2/chains"))[["name", "tvl"]].sort_values("tvl", ascending=False)


SECTORS = {"Technology": "XLK", "Financials": "XLF", "Energy": "XLE", "Health care": "XLV", "Industrials": "XLI", "Staples": "XLP",
           "Discretionary": "XLY", "Utilities": "XLU", "Materials": "XLB", "Real estate": "XLRE", "Comm. services": "XLC"}
MEGACAPS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V", "WMT", "XOM", "UNH", "LLY", "MA",
            "COST", "NFLX", "ORCL", "AMD", "BAC", "KO", "PEP", "DIS", "INTC", "CSCO"]


def _chg(tickers, names=None):
    p = safe(load_prices, {}, tuple(tickers), "1mo")
    rows = [dict(name=(names or {}).get(t, t), d1=(s.iloc[-1] / s.iloc[-2] - 1) * 100, m1=(s.iloc[-1] / s.iloc[0] - 1) * 100) for t, s in p.items()]
    return pd.DataFrame(rows)


def page_markets_plus():
    hero("🏦 Markets+ : Rates, Sectors & Valuation", "US yield curve, sector heat-map, top movers, Big Mac index and DeFi — no API keys")
    t1, t2, t3, t4 = st.tabs(["Yield curve", "Sectors & movers", "Big Mac index", "DeFi"])
    with t1:
        y = safe(load_yields, pd.DataFrame())
        if y.empty:
            st.info("Treasury data unavailable.")
        else:
            mats = [c for c in y.columns if c != "Date"]
            fig = go.Figure()
            for lab, i in (("Latest", -1), ("~1 month ago", max(0, len(y) - 22)), ("Start of year", 0)):
                fig.add_scatter(x=mats, y=y.iloc[i][mats].astype(float), mode="lines+markers", name=f"{lab} ({y.iloc[i]['Date']:%d %b})")
            clean_layout(fig, 380).update_layout(title="US Treasury yield curve (%)", yaxis_title="%")
            plot(fig)
            if "10 Yr" in y and "2 Yr" in y:
                sp = float(y["10 Yr"].iloc[-1] - y["2 Yr"].iloc[-1])
                k = st.columns(3)
                kpi(k[0], "10Y − 2Y spread", f"{sp:+.2f} pp", "Inverted (recession signal)" if sp < 0 else "Normal slope", "down" if sp < 0 else "up")
                kpi(k[1], "10Y yield", f"{y['10 Yr'].iloc[-1]:.2f}%")
                kpi(k[2], "2Y yield", f"{y['2 Yr'].iloc[-1]:.2f}%")
    with t2:
        s = _chg(SECTORS.values(), {v: k for k, v in SECTORS.items()})
        m = _chg(MEGACAPS)
        a, b = st.columns(2)
        with a:
            if not s.empty:
                fig = px.bar(s.sort_values("d1"), x="d1", y="name", orientation="h", color="d1", color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
                clean_layout(fig, 420).update_layout(title="US sectors — today (%)", coloraxis_showscale=False, yaxis_title="", xaxis_title="")
                plot(fig)
        with b:
            if not m.empty:
                mm = pd.concat([m.nlargest(6, "d1"), m.nsmallest(6, "d1")]).drop_duplicates("name").sort_values("d1")
                fig = px.bar(mm, x="d1", y="name", orientation="h", color="d1", color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
                clean_layout(fig, 420).update_layout(title="Mega-cap gainers & losers — today (%)", coloraxis_showscale=False, yaxis_title="", xaxis_title="")
                plot(fig)
    with t3:
        bm = safe(load_bigmac, pd.DataFrame())
        if bm.empty:
            st.info("Big Mac data unavailable.")
        else:
            bm["valuation_pct"] = bm["USD_raw"] * 100
            fig = px.choropleth(bm, locations="iso_a3", color="valuation_pct", hover_name="name", color_continuous_scale="RdYlGn_r", color_continuous_midpoint=0)
            plot(style_geo(fig, "World", 460))
            st.caption(f"Currency over(+)/under(−) valued vs USD by burger parity · data as of {bm['date'].iloc[0]:%b %Y} (The Economist)")
            fig = px.bar(bm.sort_values("dollar_price").tail(25), x="dollar_price", y="name", orientation="h")
            clean_layout(fig, 560).update_layout(title="Big Mac price in USD", yaxis_title="", xaxis_title="")
            plot(fig)
    with t4:
        d = safe(load_defi, pd.DataFrame())
        if d.empty:
            st.info("DefiLlama unavailable.")
        else:
            kpi(st, "Total value locked", f"${fnum(d['tvl'].sum())}")
            fig = px.bar(d.head(15).iloc[::-1], x="tvl", y="name", orientation="h", color_discrete_sequence=["#8b5cf6"])
            clean_layout(fig, 460).update_layout(title="TVL by chain (USD)", yaxis_title="", xaxis_title="")
            plot(fig)


# ---- World indices (Our World in Data) --------------------------------------
OWID = {"Human Development Index": "human-development-index", "Happiness (Cantril ladder)": "happiness-cantril-ladder",
        "Democracy index (EIU)": "democracy-index-eiu", "Corruption Perceptions Index": "ti-corruption-perception-index",
        "Press freedom index": "press-freedom-index", "Electricity from renewables (%)": "share-electricity-renewables",
        "Life expectancy": "life-expectancy", "Literacy rate (adults)": "literacy-rate-adults",
        "Gender inequality index": "gender-inequality-index-from-the-human-development-report"}


@st.cache_data(ttl=86400, show_spinner=False)
def load_owid(slug):
    t = _get_text(f"https://ourworldindata.org/grapher/{slug}.csv", {"v": 1, "csvType": "full", "useColumnShortNames": "true"}, 40)
    df = pd.read_csv(io.StringIO(t))
    df = df.rename(columns={"Entity": "country", "Code": "iso3", "Year": "year", df.columns[-1]: "value"})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["value"])[["country", "iso3", "year", "value"]]


def page_indices():
    hero("📊 World Indices", "Democracy, happiness, development, press freedom, corruption, literacy and more — via Our World in Data")
    c1, c2 = st.columns([2, 2])
    lab = c1.selectbox("Index", list(OWID) + ["Custom slug…"])
    slug = c2.text_input("OWID chart slug", "life-expectancy", help="Any slug from ourworldindata.org/grapher/<slug>") if lab == "Custom slug…" else OWID[lab]
    df = safe(load_owid, pd.DataFrame(), slug)
    if df.empty:
        st.warning("That dataset couldn't be loaded (slug may have changed). Pick another or paste a slug from ourworldindata.org.")
        return
    cur = df[df["iso3"].notna() & ~df["iso3"].astype(str).str.startswith("OWID")].sort_values("year").groupby("country").tail(1)
    fig = px.choropleth(cur, locations="iso3", color="value", hover_name="country", hover_data={"year": True, "iso3": False}, color_continuous_scale="Viridis")
    plot(style_geo(fig, st.session_state.get("region", "World"), 520))
    a, b = st.columns(2)
    for col, top in ((a, True), (b, False)):
        d = cur.nlargest(12, "value") if top else cur.nsmallest(12, "value")
        fig = px.bar(d.iloc[::-1], x="value", y="country", orientation="h", color_discrete_sequence=["#3b82f6" if top else "#f59e0b"])
        clean_layout(fig, 380).update_layout(title="Highest" if top else "Lowest", yaxis_title="", xaxis_title="")
        with col:
            plot(fig)
    sel = st.multiselect("Trend over time", sorted(cur["country"]), default=[c for c in ["United States", "China", "India", "Germany"] if c in set(cur["country"])])
    if sel:
        fig = px.line(df[df["country"].isin(sel)], x="year", y="value", color="country")
        clean_layout(fig, 360).update_layout(xaxis_title="", yaxis_title="")
        plot(fig)


# ---- Storms & volcanoes ------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def load_storms():
    d = get_json("https://www.nhc.noaa.gov/CurrentStorms.json").get("activeStorms", [])
    return pd.DataFrame([dict(name=s.get("name"), type=s.get("classification"), wind_mph=s.get("intensity"), pressure_mb=s.get("pressure"),
                              lat=s.get("latitudeNumeric"), lon=s.get("longitudeNumeric")) for s in d],
                        columns=["name", "type", "wind_mph", "pressure_mb", "lat", "lon"])


def page_storms():
    region = st.session_state.get("region", "World")
    hero("🌀 Storms & Volcanoes", "Active Atlantic/E-Pacific storms (NHC), global cyclone alerts (GDACS) and Smithsonian weekly volcano report")
    st_df = safe(load_storms, pd.DataFrame())
    gd = safe(load_gdacs, pd.DataFrame())
    cyc = gd[gd["type"] == "Tropical cyclone"].dropna(subset=["lat", "lon"]) if not gd.empty else pd.DataFrame()
    fig = go.Figure()
    if not st_df.empty:
        fig.add_scattergeo(lat=st_df["lat"], lon=st_df["lon"], text=st_df["name"] + " · " + st_df["type"].astype(str), mode="markers+text",
                           textposition="top center", name="NHC storms", marker=dict(size=16, symbol="star", color="#ef4444", line=dict(width=1, color="white")))
    if not cyc.empty:
        fig.add_scattergeo(lat=cyc["lat"], lon=cyc["lon"], text=cyc["title"], hoverinfo="text", mode="markers", name="GDACS cyclones",
                           marker=dict(size=13, symbol="triangle-up", color="#f97316", line=dict(width=1, color="white")))
    plot(style_geo(fig, region, 480))
    if st_df.empty:
        st.caption("No active NHC storms right now (normal outside hurricane season) — GDACS covers the rest of the world.")
    else:
        table(st_df)
    st.subheader("🌋 Weekly volcanic activity report")
    render_news(safe(load_rss, pd.DataFrame(), "https://volcano.si.edu/news/WeeklyVolcanoRSS.xml", "Smithsonian GVP", 30), 15, True)


# ---- Tech radar --------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def load_arxiv(cat):
    t = _get_text("https://export.arxiv.org/api/query", {"search_query": f"cat:{cat}", "sortBy": "submittedDate", "sortOrder": "descending", "max_results": 20})
    return _entries(feedparser.parse(t), "arXiv", 20)


@st.cache_data(ttl=1800, show_spinner=False)
def load_gh_trending(days):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    it = get_json("https://api.github.com/search/repositories", {"q": f"created:>{since}", "sort": "stars", "order": "desc", "per_page": 20})["items"]
    return pd.DataFrame([dict(repo=i["full_name"], stars=i["stargazers_count"], language=i.get("language"), description=(i.get("description") or "")[:140],
                              url=i["html_url"]) for i in it])


def page_tech():
    hero("💻 Tech Radar", "Latest research papers, fastest-growing GitHub repos and Hacker News — free sources")
    a, b = st.columns(2)
    with a:
        st.subheader("📄 Newest arXiv papers")
        cat = st.selectbox("Category", ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.CR", "cs.RO", "stat.ML", "physics.space-ph", "q-bio.GN", "econ.GN"])
        render_news(safe(load_arxiv, pd.DataFrame(), cat), 15, True)
    with b:
        st.subheader("⭐ New GitHub repos by stars")
        days = st.selectbox("Created in the last", [1, 7, 30], index=1, format_func=lambda x: f"{x} day(s)")
        g = safe(load_gh_trending, pd.DataFrame(), days)
        if g.empty:
            st.info("GitHub search unavailable (unauthenticated rate limit — retry in a minute).")
        else:
            table(g, column_config={"url": st.column_config.LinkColumn("Link", display_text="open")})
            lang = g["language"].value_counts().head(8).reset_index()
            lang.columns = ["language", "repos"]
            fig = px.bar(lang.iloc[::-1], x="repos", y="language", orientation="h")
            clean_layout(fig, 280).update_layout(yaxis_title="")
            plot(fig)
    st.subheader("🔶 Hacker News")
    hn = safe(load_hn, pd.DataFrame())
    for r in hn.head(10).itertuples():
        st.markdown(f"**[{esc(r.title)}]({r.url})**  \n<span class='src-tag'>▲ {r.points} · 💬 {r.comments}</span>", unsafe_allow_html=True)


# ---- Intelligence: clustered headlines, daily brief, GDELT -------------------
def cluster_titles(df, thr=0.4):
    stop = set("the and for with from after over new says say into amid how why what will has have are was its his her their about".split())
    toks = [{w for w in re.findall(r"[a-z0-9]+", t.lower()) if w not in stop and len(w) > 2} for t in df["title"]]
    cl = []
    for i, t in enumerate(toks):
        for c in cl:
            if len(t & toks[c[0]]) / max(1, len(t | toks[c[0]])) >= thr:
                c.append(i)
                break
        else:
            cl.append([i])
    return sorted(cl, key=len, reverse=True)


@st.cache_data(ttl=1800, show_spinner=False)
def load_gdelt(query, mode, span="30d"):
    d = get_json("https://api.gdeltproject.org/api/v2/doc/doc", {"query": query, "mode": mode, "format": "json", "timespan": span}, timeout=40)
    pts = (d.get("timeline") or [{}])[0].get("data", [])
    return pd.DataFrame([dict(date=pd.to_datetime(p["date"], format="%Y%m%dT%H%M%SZ"), value=p["value"]) for p in pts])


def page_intel():
    hero("🧠 Intelligence Desk", "Headlines clustered by story, an auto-generated daily brief you can download, and media tone tracking (GDELT)")
    srcs = tuple(NEWS_FEEDS["World"])
    news = safe(load_news, pd.DataFrame(), "World", srcs)
    quakes, gd = safe(load_quakes, pd.DataFrame(), "2.5_day"), safe(load_gdacs, pd.DataFrame())
    mdf, _ = market_frame("1mo")
    brief = [f"# World brief — {datetime.now(timezone.utc):%d %b %Y %H:%M UTC}", "", "## Top stories (by number of outlets)"]
    st.subheader("🗞️ Stories covered by the most outlets")
    if news.empty:
        st.info("News unavailable.")
    else:
        for c in cluster_titles(news.head(150))[:10]:
            sub = news.head(150).iloc[c]
            outlets = ", ".join(sorted(set(sub["source"])))
            lead = sub.iloc[0]
            st.markdown(f"**[{esc(lead['title'])}]({lead['link']})**  \n<span class='src-tag'>{len(set(sub['source']))} outlet(s): {outlets}</span>", unsafe_allow_html=True)
            brief.append(f"- {lead['title']} ({outlets})")
    brief += ["", "## Hazards"]
    if not quakes.empty:
        q = quakes.loc[quakes["magnitude"].idxmax()]
        brief.append(f"- {len(quakes)} earthquakes M2.5+ in 24h; strongest M{q['magnitude']:.1f} — {q['place']}")
    if not gd.empty:
        for x in gd[gd["alert"].isin(["Orange", "Red"])].head(6).itertuples():
            brief.append(f"- GDACS {x.alert}: {x.title}")
    brief += ["", "## Markets (1-day)"]
    if not mdf.empty:
        for x in pd.concat([mdf.nlargest(3, "chg_1d"), mdf.nsmallest(3, "chg_1d")]).itertuples():
            brief.append(f"- {x.name}: {x.chg_1d:+.2f}%")
    md = "\n".join(brief)
    with st.expander("📋 Daily brief (markdown)", expanded=False):
        st.markdown(md)
    st.download_button("⬇ Download daily brief (.md)", md.encode(), f"world_brief_{datetime.now():%Y%m%d}.md", "text/markdown")
    st.subheader("🎭 Media tone & volume (GDELT)")
    q = st.text_input("Topic, country or company", "Ukraine")
    span = st.selectbox("Window", ["7d", "30d", "90d"], index=1)
    a, b = st.columns(2)
    for col, mode, ttl in ((a, "timelinetone", "Average tone (negative = bad news)"), (b, "timelinevolraw", "Article volume")):
        d = safe(load_gdelt, pd.DataFrame(), q, mode, span)
        with col:
            if d.empty:
                st.info("GDELT unavailable or rate-limited (1 request / 5 s). Retry shortly.")
            else:
                fig = px.area(d, x="date", y="value", color_discrete_sequence=["#ef4444" if mode == "timelinetone" else "#3b82f6"])
                clean_layout(fig, 300).update_layout(title=ttl, xaxis_title="", yaxis_title="")
                plot(fig)




# =============================================================================
# NAVIGATION & SIDEBAR
# =============================================================================
pages = [
    st.Page(page_overview, title="Command Center", icon="🌐", url_path="overview", default=True),
    st.Page(page_maps, title="Continents & Maps", icon="🗺️", url_path="maps"),
    st.Page(page_country, title="Country Explorer", icon="🏳️", url_path="country"),
    st.Page(page_compare, title="Compare Countries", icon="⚖️", url_path="compare"),
    st.Page(page_health, title="Health & Outbreaks", icon="🦠", url_path="health"),
    st.Page(page_news, title="News Room", icon="📰", url_path="news"),
    st.Page(page_markets, title="Markets & FX", icon="📈", url_path="markets"),
    st.Page(page_weather, title="Weather & Air", icon="🌦️", url_path="weather"),
    st.Page(page_hazards, title="Earth & Hazards", icon="🌋", url_path="hazards"),
    st.Page(page_space, title="Space & Sky", icon="🚀", url_path="space"),
    st.Page(page_cams, title="Live Cams & Imagery", icon="📹", url_path="cams"),
    st.Page(page_trending, title="Trending", icon="🔥", url_path="trending"),
    st.Page(page_status, title="Source Status", icon="🩺", url_path="status"),
    st.Page(page_passports, title="Passport Power", icon="🛂", url_path="passports"),
    st.Page(page_climate,   title="Climate Watch",  icon="🌡️", url_path="climate"),
    st.Page(page_aviation,  title="Live Flights",   icon="✈️", url_path="flights"),
    st.Page(page_cyber,     title="Cyber & Internet", icon="🛡️", url_path="cyber"),
    st.Page(page_calendar,  title="Calendar & Society", icon="📅", url_path="calendar"),
    st.Page(page_markets_plus, title="Markets+",       icon="🏦", url_path="marketsplus"),
    st.Page(page_indices,      title="World Indices",  icon="📊", url_path="indices"),
    st.Page(page_storms,       title="Storms & Volcanoes", icon="🌀", url_path="storms"),
    st.Page(page_tech,         title="Tech Radar",     icon="💻", url_path="tech"),
    st.Page(page_intel,        title="Intelligence Desk", icon="🧠", url_path="intel"),
]
pg = st.navigation(pages)

with st.sidebar:
    st.markdown("---")
    st.selectbox("🌐 Region focus (maps)", list(REGIONS), key="region")
    auto = st.selectbox("⏱️ Auto-refresh", ["Off", "1 min", "5 min", "15 min"], key="auto")
    if auto != "Off":
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval={"1 min": 60, "5 min": 300, "15 min": 900}[auto] * 1000, key="autoref")
        except Exception:  # noqa: BLE001
            st.caption("Install `streamlit-autorefresh` to enable this.")
    if st.button("🔄 Refresh all data"):
        st.cache_data.clear()
        st.session_state["_fails"] = {}
        st.rerun()
    st.caption(f"Loaded {datetime.now(timezone.utc):%d %b %Y %H:%M UTC}")
    error_box = st.empty()

ticker()
pg.run()

if ERRORS:
    with error_box.expander(f"⚠️ {len(ERRORS)} source issue(s)"):
        for e in ERRORS:
            st.caption(e)
else:
    error_box.success("All sources loaded")
