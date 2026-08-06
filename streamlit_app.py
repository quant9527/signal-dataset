"""Streamlit entrypoint: registers 8 sections / 24 pages under app_pages/.

Each page is registered as an `st.Page` with a unique `url_path`, so the
app uses Streamlit's path-based multipage navigation (`st.navigation`).
URLs are first-class: every signal page is independently addressable,
bookmarkable, shareable, and refresh-safe.

`st.navigation` renders a section-grouped sidebar by default, which is
what we want — the navigation lives in the sidebar, and the main area
runs only the currently routed page.
"""
from __future__ import annotations

import streamlit as st

# Pages are imported for their module-level `page_<name>()` callables.
from app_pages.active_vol_then_nestedbc import page_active_vol_then_nestedbc
from app_pages.alert_rule_crud import page_alert_rule_crud
from app_pages.all_signals_by_symbol import page_all_signals_by_symbol
from app_pages.backtest_report_detail import page_backtest_report_detail
from app_pages.backtest_reports import page_backtest_reports
from app_pages.dashboard_as import page_dashboard_as
from app_pages.dashboard_binance import page_dashboard_binance
from app_pages.dashboard_em import page_dashboard_em
from app_pages.instrument_groups import page_instrument_groups
from app_pages.kline_fullscreen import page_kline_fullscreen
from app_pages.main_then_yd import page_main_then_yd
from app_pages.ml_scores import page_ml_scores
from app_pages.nested_bc import page_nested_bc
from app_pages.overview import page_overview
from app_pages.performance import page_performance
from app_pages.profit_pattern_cl3b_zsx import page_profit_pattern_cl3b_zsx
from app_pages.review_em import page_review_em
from app_pages.review_hotspot import page_review_hotspot
from app_pages.review_index import page_review_index
from app_pages.review_key import page_review_key
from app_pages.review_today import page_review_today
from app_pages.search_signals import page_search_signals
from app_pages.sector_signals import page_sector_signals
from app_pages.signal_bc_xd4 import page_signal_bc_xd4
from app_pages.signal_cl2b_pair import page_signal_cl2b_pair
from app_pages.today_opportunities import page_today_opportunities

pages: dict[str, list[st.StreamlitPage]] = {
    "Dashboard": [
        st.Page(page_dashboard_as,      title="AS",      icon="🇨🇳", url_path="dashboard_as"),
        st.Page(page_dashboard_binance, title="Binance", icon="🪙",  url_path="dashboard_binance"),
        st.Page(page_dashboard_em,      title="EM",      icon="🌍", url_path="dashboard_em"),
    ],
    "AS": [
        st.Page(page_today_opportunities, title="今日机会", icon="🎯",
                url_path="today_opportunities", default=True),
        st.Page(page_review_index,            title="大盘",     icon="📈", url_path="review_index"),
        st.Page(page_review_hotspot,          title="板块热点", icon="🔥", url_path="review_hotspot"),
        st.Page(page_active_vol_then_nestedbc, title="active_vol_then_nestedbc",
                icon="📉", url_path="active_vol_then_nestedbc"),
        st.Page(page_nested_bc,               title="nested_bc", icon="📊", url_path="nested_bc"),
        st.Page(page_profit_pattern_cl3b_zsx, title="CL3B ZSX",  icon="📈",
                url_path="profit_pattern_cl3b_zsx"),
        st.Page(page_main_then_yd,            title="主→yd",      icon="🔗", url_path="main_then_yd"),
    ],
    "K线": [
        st.Page(page_kline_fullscreen, title="K线", icon="🕯️", url_path="kline"),
    ],
    "Review": [
        st.Page(page_overview,    title="Overview",     icon="🏠", url_path="overview"),
        st.Page(page_review_today, title="Today Review", icon="📋", url_path="review_today"),
        st.Page(page_review_em,    title="EM Review",    icon="📋", url_path="review_em"),
        st.Page(page_review_key,   title="Key Review",   icon="⭐", url_path="review_key"),
    ],
    "Reports": [
        st.Page(page_backtest_reports, title="Backtest Reports", icon="📈",
                url_path="backtest_reports"),
        st.Page(page_backtest_report_detail, title="Backtest Report Detail",
                icon="📑", url_path="backtest_report_detail"),
    ],
    "Performance": [
        st.Page(page_performance, title="Performance", icon="📊", url_path="performance"),
    ],
    "Signals": [
        st.Page(page_all_signals_by_symbol, title="All Signals by Symbol", icon="📊",
                url_path="all_signals_by_symbol"),
        st.Page(page_sector_signals,         title="Sector Signals",        icon="🏢",
                url_path="sector_signals"),
        st.Page(page_search_signals,         title="Search Signals",        icon="🔍",
                url_path="search_signals"),
    ],
    "AS 模式": [
        st.Page(page_signal_cl2b_pair, title="CL2B Pair", icon="🔎",
                url_path="signal_cl2b_pair"),
        st.Page(page_signal_bc_xd4, title="BC XD4", icon="📉",
                url_path="signal_bc_xd4"),
    ],
    "Tools": [
        st.Page(page_instrument_groups, title="Instrument Groups", icon="📁",
                url_path="instrument_groups"),
        st.Page(page_alert_rule_crud,   title="Alert Rules",      icon="🔔",
                url_path="alert_rule_crud"),
    ],
    "ML": [
        st.Page(page_ml_scores, title="ML Scores", icon="🤖", url_path="ml_scores"),
    ],
}

# Render section-grouped navigation in the sidebar (Streamlit's default).
# Each entry's `url_path` makes the page directly addressable, e.g.
# /today_opportunities, /review_index, /kline_fullscreen, /ml_scores.
pg = st.navigation(pages)
pg.run()