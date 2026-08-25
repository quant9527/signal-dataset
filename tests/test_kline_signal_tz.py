"""Regression test: kline_charts.map_signals_to_bars must accept tz-aware signal_date.

背景：用户报告 `http://localhost:8501/kline?symbol=asindex:sh000131:1w&start=2026-07-03&end=2026-07-31`
页面打开报错。根因：当 `data.get_kline_signals` 返回的 DataFrame 中 `signal_date`
是 tz-aware（来自 PostgreSQL timestamptz 经 psycopg/psycopg2 直出），而 `prep["_x"]`
被 `_prepare_kline_frame` 显式转 tz-naive；`map_signals_to_bars` 的 intraday 路径里
`(bdt - sig_dt).total_seconds()` 会抛
`TypeError: Cannot subtract tz-naive and tz-aware datetime-like objects.`。

修复：在 map_signals_to_bars 入口处把 bar_dates 和 sig_dt 都统一剥 tz，容忍任意上游输入。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app_pages.kline_charts import map_signals_to_bars


def _sig_row(signal_date, **extra):
    base = {
        "signal_date": signal_date,
        "signal_name": "t",
        "side": "long",
        "signal": "BUY",
        "freq": "1h",
        "price": 100.0,
        "reason": "",
        "score": 1.0,
    }
    base.update(extra)
    return base


def test_intraday_tz_aware_signal_does_not_crash():
    """修复前会抛 TypeError；修复后必须正常返回 barIndex。"""
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2026-07-18 09:30", "2026-07-18 10:30", "2026-07-18 11:30"]),
        "close": [100, 101, 102],
    })
    sigs = pd.DataFrame([_sig_row(
        pd.Timestamp("2026-07-18 10:00", tz="Asia/Shanghai"),
        freq="1h",
    )])
    result = map_signals_to_bars(prep, sigs, chart_freq=None)
    assert len(result) == 1
    # 10:00 距离 09:30/10:30 都是 30 min，first match wins → barIndex 0 或 1 都合理
    assert result[0]["barIndex"] in (0, 1)


def test_intraday_python_datetime_tz_aware():
    """psycopg 直出的 tz-aware datetime.datetime 也不能崩。"""
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2026-07-18 10:30", "2026-07-18 11:30", "2026-07-18 12:30"]),
        "close": [100, 101, 102],
    })
    sigs = pd.DataFrame([_sig_row(
        datetime(2026, 7, 18, 10, 0, tzinfo=timezone(timedelta(hours=8))),
        freq="1h",
    )])
    result = map_signals_to_bars(prep, sigs, chart_freq=None)
    assert len(result) == 1
    assert result[0]["barIndex"] == 0  # 10:30 是离 10:00 最近的 bar


def test_daily_tz_aware_signal_matches_by_date_part():
    """日线/周线分支：按 date() 匹配，tz-aware 也能正常工作。"""
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2026-07-17", "2026-07-18", "2026-07-19"]),
        "close": [100, 101, 102],
    })
    sigs = pd.DataFrame([_sig_row(
        pd.Timestamp("2026-07-18 10:00", tz="Asia/Shanghai"),
        freq="1d",
    )])
    result = map_signals_to_bars(prep, sigs, chart_freq=None)
    assert len(result) == 1
    assert result[0]["barIndex"] == 1


def test_daily_naive_signal_still_works():
    """原有 tz-naive 路径不能回归。"""
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2026-07-17", "2026-07-18", "2026-07-19"]),
        "close": [100, 101, 102],
    })
    sigs = pd.DataFrame([_sig_row(pd.Timestamp("2026-07-18"), freq="1d")])
    result = map_signals_to_bars(prep, sigs, chart_freq=None)
    assert len(result) == 1
    assert result[0]["barIndex"] == 1


def test_empty_signals_returns_empty_list():
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2026-07-18"]),
        "close": [100],
    })
    assert map_signals_to_bars(prep, pd.DataFrame(), chart_freq=None) == []