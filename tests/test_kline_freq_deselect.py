"""K 线页面「取消周期即隐藏」的 Streamlit AppTest 交互测试。"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from symbol_picker import parse_symbol_tokens


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
    st.session_state.setdefault("recorded_tags", []).append(
        (list(tags), bool(kline_reverse), str(st.query_params.get("symbol", "")))
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
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "vol": 100,
            "ma5": 1.0,
            "macd": 0.0,
            "dif": 0.0,
            "dea": 0.0,
            "pct_change": 0.0,
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


@pytest.fixture
def at(tmp_path):
    runner = tmp_path / "kline_runner.py"
    runner.write_text(RUNNER_TEMPLATE)
    app = AppTest.from_file(str(runner))
    app.query_params["symbol"] = "as:000001:1d,ths:600519:1h"
    app.query_params["start"] = "2025-01-01"
    app.query_params["end"] = "2025-01-10"
    app.query_params["all_signals"] = "0"
    return app


def _last_tags(app):
    try:
        recorded = app.session_state["recorded_tags"]
    except KeyError:
        return []
    if not recorded:
        return []
    return recorded[-1][0]


def _set_freq(app, key, freq):
    """AppTest 的 pills.set_value(None) 不会清空单选，直接改 session_state。"""
    app.session_state[key] = freq


def _qp_value(app, key):
    """AppTest 的 query_params 可能返回 list，统一取第一个值。"""
    value = app.query_params[key]
    if isinstance(value, list):
        return value[0] if value else ""
    return value


def _is_all_hidden(symbol_qs: str) -> bool:
    entries = parse_symbol_tokens(symbol_qs)
    return bool(entries) and all(e.freq is None for e in entries)


def test_deselect_first_symbol_hides_chart(at):
    at.run()
    _set_freq(at, "kfs_freq_pills_0_as_000001", None)
    at.run()

    assert _qp_value(at, "symbol") == "as:000001,ths:600519:1h"
    last_tags = _last_tags(at)
    assert "as_000001_1d" not in last_tags
    assert "ths_600519_1h" in last_tags


def test_reselect_period_restores_chart(at):
    at.run()
    _set_freq(at, "kfs_freq_pills_0_as_000001", None)
    at.run()
    _set_freq(at, "kfs_freq_pills_0_as_000001", "1h")
    at.run()

    assert "as:000001:1h" in _qp_value(at, "symbol")
    last_tags = _last_tags(at)
    assert "as_000001_1h" in last_tags


def test_all_hidden_shows_info_and_stops(at):
    at.run()
    _set_freq(at, "kfs_freq_pills_0_as_000001", None)
    at.run()
    _set_freq(at, "kfs_freq_pills_1_ths_600519", None)
    at.run()

    assert _qp_value(at, "symbol") == "as:000001,ths:600519"
    info_texts = [i.value for i in at.info]
    assert any("所有标的均已隐藏" in t for t in info_texts)
    # 全部 hidden 的状态下不应发起 Flight 请求
    recorded = at.session_state["recorded_tags"]
    assert not any(_is_all_hidden(sym_qs) for _, _, sym_qs in recorded)


def test_remove_front_entry_preserves_hidden_state(at):
    """删除前置 entry 后，后续 hidden entry 不应因 pills key 索引漂移而被重新选中。"""
    at.query_params["symbol"] = "as:000001:1d,ths:600519"
    at.run()
    # 后置 entry 初始为 hidden
    assert at.pills(key="kfs_freq_pills_1_ths_600519").value is None

    at.button(key="kfs_rm_0").click().run()

    assert _qp_value(at, "symbol") == "ths:600519"
    assert at.pills(key="kfs_freq_pills_0_ths_600519").value is None
    info_texts = [i.value for i in at.info]
    assert any("所有标的均已隐藏" in t for t in info_texts)


def test_clear_button_resets_to_default(at):
    at.run()
    assert _qp_value(at, "symbol") == "as:000001:1d,ths:600519:1h"

    at.button(key="kfs_clear").click().run()

    assert at.query_params.get("symbol", "") in ("", [], None)
    assert at.query_params.get("start", "") in ("", [], None)
    assert at.query_params.get("end", "") in ("", [], None)
    assert at.query_params.get("all_signals", "") in ("", [], None)
    info_texts = [i.value for i in at.info]
    assert any("请通过「添加标的」" in t for t in info_texts)


def test_quick_add_with_first_hidden_uses_default_freq(at):
    """首个 entry 为 hidden 时，快捷添加不应继承 None，而应使用默认周期。"""
    at.query_params["symbol"] = "as:000001,ths:600519:1h"
    at.run()

    at.button(key="kfs_quick_btn_0").click().run()

    symbol = _qp_value(at, "symbol")
    assert "asindex:sh000300:1d" in symbol
    # 新添加的标的应参与 Flight 请求
    last_tags = _last_tags(at)
    assert any("asindex_sh000300_1d" in tag for tag in last_tags)


def test_same_symbol_multiple_freqs_no_duplicate_key(tmp_path):
    """同一只标的以不同频率同时出现时，不应触发 StreamlitDuplicateElementKey。"""
    runner = tmp_path / "kline_same_symbol_runner.py"
    runner.write_text(RUNNER_TEMPLATE)
    app = AppTest.from_file(str(runner))
    app.query_params["symbol"] = "as:000001:1d,as:000001:1h"
    app.query_params["start"] = "2025-01-01"
    app.query_params["end"] = "2025-01-10"
    app.query_params["all_signals"] = "0"

    app.run()
    # 不应存在 exception（修复前会抛 StreamlitDuplicateElementKey）
    assert not app.exception
    # 应发起 Flight 请求，分别覆盖 1d 与 1h（分组调用可能有多个记录）
    try:
        recorded = app.session_state["recorded_tags"]
    except KeyError:
        recorded = []
    all_tags = [tag for rec in recorded for tag in rec[0]]
    assert any("as_000001_1d" in tag for tag in all_tags)
    assert any("as_000001_1h" in tag for tag in all_tags)
