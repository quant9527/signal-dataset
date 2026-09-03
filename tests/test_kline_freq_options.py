"""K 线周期列表按交易所类型（ashare / crypto）区分的测试。"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from constants import (
    KLINE_FREQ_OPTIONS_AS,
    KLINE_FREQ_OPTIONS_CRYPTO,
    KLINE_FREQ_SET,
    kline_freq_options_for_exchange,
)


RUNNER_TEMPLATE = r'''
import pandas as pd
import streamlit as st

import app_pages.kline_charts as kc
import data
import flight_kline_client as fkc


def fake_get_instruments_by_exchange(exchange):
    return pd.DataFrame({"symbol": [], "name": []})


def fake_get_kline_signals(exchange, symbol, start_d, end_d, freq=None):
    return pd.DataFrame({
        "signal_date": pd.to_datetime([]),
        "signal_name": [],
        "side": [],
        "signal": [],
        "freq": [],
        "price": [],
        "reason": [],
        "score": [],
    })


def fake_fetch_kline_dataframe(tags, start_ms, end_ms, flight_url=None, kline_reverse=False, kline_aggregate=""):
    st.session_state.setdefault("recorded", []).append(
        {"tags": list(tags), "aggregate": str(kline_aggregate)}
    )
    rows = []
    for tag in tags:
        parts = tag.split("_")
        if len(parts) < 3:
            continue
        exchange, symbol, freq = parts[0], parts[1], parts[2]
        rows.append({
            "symbol": symbol,
            "exchange": exchange,
            "end_ts": start_ms,
            "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "vol": 100,
            "ma5": 1.0, "macd": 0.0, "dif": 0.0, "dea": 0.0, "pct_change": 0.0,
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def fake_resolve_flight_url():
    return ""


data.get_instruments_by_exchange = fake_get_instruments_by_exchange
data.get_kline_signals = fake_get_kline_signals
fkc.fetch_kline_dataframe = fake_fetch_kline_dataframe
kc.resolve_flight_url = fake_resolve_flight_url

from app_pages.kline_fullscreen import page_kline_fullscreen

page_kline_fullscreen()
'''


@pytest.mark.parametrize(
    ("exchange", "expected"),
    [
        ("as", KLINE_FREQ_OPTIONS_AS),
        ("ths", KLINE_FREQ_OPTIONS_AS),
        ("asindex", KLINE_FREQ_OPTIONS_AS),
        ("em", KLINE_FREQ_OPTIONS_AS),
        ("as_all", KLINE_FREQ_OPTIONS_AS),
        ("hyperliquid", KLINE_FREQ_OPTIONS_CRYPTO),
        ("binance", KLINE_FREQ_OPTIONS_CRYPTO),
        ("binancespot", KLINE_FREQ_OPTIONS_CRYPTO),
        ("crypto", KLINE_FREQ_OPTIONS_CRYPTO),
        ("HyperLiquid", KLINE_FREQ_OPTIONS_CRYPTO),
        ("unknown", KLINE_FREQ_OPTIONS_AS),
        ("", KLINE_FREQ_OPTIONS_AS),
    ],
)
def test_freq_options_by_exchange(exchange, expected):
    assert kline_freq_options_for_exchange(exchange) == expected


def test_crypto_only_freqs_excluded_from_as():
    crypto_only = set(KLINE_FREQ_OPTIONS_CRYPTO) - set(KLINE_FREQ_OPTIONS_AS)
    assert crypto_only == {"1M", "12h", "8h", "6h", "4h", "3m", "1m"}


def test_union_freq_set_for_url_protocol():
    assert KLINE_FREQ_SET == frozenset((*KLINE_FREQ_OPTIONS_AS, *KLINE_FREQ_OPTIONS_CRYPTO))


@pytest.fixture
def at(tmp_path):
    runner = tmp_path / "kline_freq_runner.py"
    runner.write_text(RUNNER_TEMPLATE)
    app = AppTest.from_file(str(runner))
    app.query_params["symbol"] = "as:000001:1d,hyperliquid:DASHUSDT:1d"
    app.query_params["start"] = "2025-01-01"
    app.query_params["end"] = "2025-01-10"
    app.query_params["all_signals"] = "0"
    return app


def _pills_options(app, key):
    return list(app.pills(key=key).options)


def _qp_value(app, key):
    value = app.query_params[key]
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def test_mixed_exchanges_get_their_own_pills(at):
    at.run()

    assert _pills_options(at, "kfs_freq_pills_0_as_000001") == list(KLINE_FREQ_OPTIONS_AS)
    crypto_options = _pills_options(at, "kfs_freq_pills_1_hyperliquid_DASHUSDT")
    assert crypto_options == list(KLINE_FREQ_OPTIONS_CRYPTO)
    assert "4h" in crypto_options


def test_hyperliquid_can_select_crypto_freq(at):
    at.run()
    at.pills(key="kfs_freq_pills_1_hyperliquid_DASHUSDT").set_value("4h").run()

    assert "hyperliquid:DASHUSDT:4h" in _qp_value(at, "symbol")
    last = at.session_state["recorded"][-1]
    assert "hyperliquid_DASHUSDT_4h" in last["tags"]
    assert last["aggregate"] == ""


def test_hyperliquid_derived_freq_uses_1d_base(at):
    at.run()
    at.pills(key="kfs_freq_pills_1_hyperliquid_DASHUSDT").set_value("1M").run()

    assert "hyperliquid:DASHUSDT:1M" in _qp_value(at, "symbol")
    last = at.session_state["recorded"][-1]
    assert "hyperliquid_DASHUSDT_1d" in last["tags"]
    assert last["aggregate"] == "1M"
