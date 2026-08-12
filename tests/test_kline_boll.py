"""kline_charts.py 布林带（BOLL）相关单元测试。"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app_pages.kline_charts import (
    BOLL_WINDOW,
    _prepare_kline_frame,
    build_chart_meta,
    build_symbol_candle_option,
    to_echarts_boll,
)


def _fake_frame(n: int = 40) -> pd.DataFrame:
    base = pd.Timestamp("2025-01-01", tz="UTC")
    ts = [int((base + pd.Timedelta(days=i)).timestamp() * 1000) for i in range(n)]
    close = [10.0 + math.sin(i / 3) for i in range(n)]
    return pd.DataFrame({
        "end_ts": ts,
        "open": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "close": close,
        "vol": [1000] * n,
    })


def test_prepare_kline_frame_computes_boll() -> None:
    parsed = _prepare_kline_frame(_fake_frame())
    assert parsed is not None
    prep, _meta = parsed
    for col in ("_boll_upper", "_boll_mid", "_boll_lower"):
        assert col in prep.columns

    # 前 BOLL_WINDOW-1 根无值，第 BOLL_WINDOW 根起有值
    mid = prep["_boll_mid"]
    assert mid.iloc[: BOLL_WINDOW - 1].isna().all()
    assert mid.iloc[BOLL_WINDOW - 1 :].notna().all()

    # 中轨 = 收盘价的 20 周期 SMA（按时间排序后）
    closes = prep["close"].to_numpy()
    expected_mid = closes[:BOLL_WINDOW].mean()
    assert np.isclose(mid.iloc[BOLL_WINDOW - 1], expected_mid)

    # 上下轨 = 中轨 ± 2 * 总体标准差（ddof=0）
    std = closes[:BOLL_WINDOW].std(ddof=0)
    assert np.isclose(prep["_boll_upper"].iloc[BOLL_WINDOW - 1], expected_mid + 2 * std)
    assert np.isclose(prep["_boll_lower"].iloc[BOLL_WINDOW - 1], expected_mid - 2 * std)


def test_prepare_kline_frame_boll_respects_time_order() -> None:
    """乱序输入也应按时间排序后再算 rolling。"""
    df = _fake_frame().sample(frac=1.0, random_state=7)
    parsed = _prepare_kline_frame(df)
    assert parsed is not None
    prep, _meta = parsed
    expected_mid = prep["close"].iloc[:BOLL_WINDOW].mean()
    assert np.isclose(prep["_boll_mid"].iloc[BOLL_WINDOW - 1], expected_mid)


def test_to_echarts_boll_returns_three_lines() -> None:
    parsed = _prepare_kline_frame(_fake_frame())
    assert parsed is not None
    prep, _meta = parsed
    lines = to_echarts_boll(prep)
    assert [line["name"] for line in lines] == ["BOLL上", "BOLL中", "BOLL下"]
    assert all(len(line["data"]) == len(prep) for line in lines)
    # 不足窗口的位置为 None
    assert lines[0]["data"][0] is None
    assert lines[0]["data"][BOLL_WINDOW - 1] is not None


def test_to_echarts_boll_empty_when_insufficient_bars() -> None:
    parsed = _prepare_kline_frame(_fake_frame(n=5))
    assert parsed is not None
    prep, _meta = parsed
    assert to_echarts_boll(prep) == []


def test_option_includes_boll_series_and_legend() -> None:
    parsed = _prepare_kline_frame(_fake_frame())
    assert parsed is not None
    prep, _meta = parsed
    boll_lines = to_echarts_boll(prep)
    option = build_symbol_candle_option(
        title="t",
        labels=["2025-01-01"] * len(prep),
        ohlc=[[1.0, 1.0, 1.0, 1.0]] * len(prep),
        volume=[],
        ma_lines=[],
        macd=None,
        has_volume=False,
        boll_lines=boll_lines,
    )
    names = [s["name"] for s in option["series"]]
    for b in ("BOLL上", "BOLL中", "BOLL下"):
        assert b in names
        assert b in option["legend"]["data"]
    boll_series = next(s for s in option["series"] if s["name"] == "BOLL上")
    assert boll_series["lineStyle"]["type"] == "dashed"


def test_chart_meta_includes_boll() -> None:
    parsed = _prepare_kline_frame(_fake_frame())
    assert parsed is not None
    prep, _meta = parsed
    boll_lines = to_echarts_boll(prep)
    meta = build_chart_meta(
        ["2025-01-01"] * len(prep),
        [[1.0, 1.0, 1.0, 1.0]] * len(prep),
        [],
        [],
        boll_lines=boll_lines,
    )
    assert [b["name"] for b in meta["boll"]] == ["BOLL上", "BOLL中", "BOLL下"]


def test_boll_values_match_manual_calculation() -> None:
    """与 numpy 手工计算逐点比对。"""
    parsed = _prepare_kline_frame(_fake_frame())
    assert parsed is not None
    prep, _meta = parsed
    closes = prep["close"].to_numpy()
    for i in range(BOLL_WINDOW - 1, len(prep)):
        window = closes[i - BOLL_WINDOW + 1 : i + 1]
        m = window.mean()
        s = window.std(ddof=0)
        assert np.isclose(prep["_boll_mid"].iloc[i], m)
        assert np.isclose(prep["_boll_upper"].iloc[i], m + 2 * s)
        assert np.isclose(prep["_boll_lower"].iloc[i], m - 2 * s)
