"""kline_fullscreen.py 纯函数 helper 的单元测试。"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

import app_pages.kline_fullscreen as kfs
from symbol_picker import SymbolToken


def test_group_entries_skips_hidden():
    entries = [
        SymbolToken("as", "000001", "1d", False),
        SymbolToken("ths", "600519", None, False),
        SymbolToken("as", "000002", "1h", True),
    ]
    groups = kfs._group_entries(entries)
    assert set(groups.keys()) == {("1d", False), ("1h", True)}
    assert groups[("1d", False)] == [SymbolToken("as", "000001", "1d", False)]
    assert groups[("1h", True)] == [SymbolToken("as", "000002", "1h", True)]


def test_build_charts_skips_hidden_entries():
    """_build_charts 只渲染可见 entry，并正确计算图表高度（基于可见数）。"""
    entries = [
        SymbolToken("as", "000001", "1d", False),
        SymbolToken("ths", "600519", None, False),
    ]
    frames = {
        ("1d", False): pd.DataFrame({"symbol": ["000001"], "close": [1.0]}),
    }

    fake_prep = pd.DataFrame({
        "_x": pd.to_datetime(["2025-01-01"]),
        "volume": [100],
        "pct_change": [0.0],
    })
    fake_meta = {"ma_cols": [], "macd": {}, "has_volume": True}

    with (
        patch.object(kfs.fkc, "build_kline_tags", return_value=["as_000001_1d"]),
        patch.object(kfs.kc, "symbol_key_from_tags", return_value="000001"),
        patch.object(kfs.kc, "extract_symbol_data", return_value=(fake_prep, fake_meta)),
        patch.object(kfs.kc, "date_labels", return_value=["2025-01-01"]),
        patch.object(kfs.kc, "to_echarts_ohlc", return_value=[]),
        patch.object(kfs.kc, "to_echarts_volume", return_value=[]),
        patch.object(kfs.kc, "to_echarts_ma", return_value=[]),
        patch.object(kfs.kc, "to_echarts_macd", return_value={}),
        patch.object(kfs.kc, "build_symbol_candle_option", return_value={"id": "ch_0"}),
        patch.object(kfs.kc, "build_chart_meta", return_value={}),
        patch.object(kfs.data, "get_kline_signals", return_value=pd.DataFrame()),
    ):
        charts, metas, bar_counts = kfs._build_charts(
            entries, frames, date(2025, 1, 1), date(2025, 1, 2)
        )

    assert len(charts) == 1
    assert "ths:600519" not in bar_counts
    assert charts[0]["height"] == kfs._symbol_chart_height(1)
