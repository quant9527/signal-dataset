"""K 线 URL 编解码与信号字段映射的验证测试。"""

from __future__ import annotations

import pandas as pd

from symbol_picker import SymbolToken, encode_symbol_token, parse_symbol_tokens
from app_pages.kline_charts import (
    _build_signal_arrow_series,
    build_chart_meta,
    build_echarts_html,
    date_labels,
    extract_symbol_data,
    map_signals_to_bars,
    to_echarts_ohlc,
    to_echarts_volume,
)


# ---------- URL 编解码 ----------


def test_encode_basic() -> None:
    assert encode_symbol_token("as", "000001", "1d", False) == "as:000001:1d"


def test_encode_reverse() -> None:
    assert encode_symbol_token("asindex", "sh000300", "1w", True) == "asindex:sh000300:1w:reverse"


def test_encode_invalid_freq_falls_back() -> None:
    assert encode_symbol_token("as", "000001", "9x", False) == "as:000001:1d"


def test_parse_multiple_tokens() -> None:
    entries = parse_symbol_tokens("as:000001:1d,asindex:sh000300:1w:reverse")
    assert entries == [
        SymbolToken("as", "000001", "1d", False),
        SymbolToken("asindex", "sh000300", "1w", True),
    ]


def test_parse_roundtrip() -> None:
    raw = "as:000001:1d,ths:600519:30m,hyperliquid:BTC:1h:reverse"
    entries = parse_symbol_tokens(raw)
    assert ",".join(e.token for e in entries) == raw


def test_parse_missing_freq_means_hidden() -> None:
    entries = parse_symbol_tokens("as:000001,,:badfreq,as:000002:5m")
    assert entries == [
        SymbolToken("as", "000001", None, False),
        SymbolToken("as", "000002", "5m", False),
    ]


def test_encode_none_freq() -> None:
    assert encode_symbol_token("as", "000001", None, False) == "as:000001"


def test_encode_none_freq_with_reverse() -> None:
    assert encode_symbol_token("as", "000001", None, True) == "as:000001:reverse"


def test_parse_none_freq_with_reverse() -> None:
    entries = parse_symbol_tokens("as:000001:reverse")
    assert entries == [SymbolToken("as", "000001", None, True)]


def test_parse_hidden_roundtrip() -> None:
    raw = "as:000001,ths:600519:1d,hyperliquid:BTC:1h:reverse"
    entries = parse_symbol_tokens(raw)
    assert ",".join(e.token for e in entries) == raw


def test_parse_empty() -> None:
    assert parse_symbol_tokens("") == []
    assert parse_symbol_tokens(None) == []


# ---------- 信号字段映射 ----------


def _fake_prep() -> pd.DataFrame:
    return pd.DataFrame({"_x": pd.to_datetime(["2025-01-02", "2025-01-03"])})


def _fake_signals() -> pd.DataFrame:
    return pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03"]),
        "signal_name": ["strat_a", "strat_b", "strat_a"],
        "side": ["long", "long", "short"],
        "signal": ["BUY", "BUY", "SELL"],
        "freq": ["1d", "1d", "1d"],
        "price": [10.5, 10.6, 11.2],
        "reason": ["r1", "r2", "r3"],
        "score": [0.87, None, -0.5],
    })


def test_map_signals_fields() -> None:
    mapped = map_signals_to_bars(_fake_prep(), _fake_signals())
    assert [m["barIndex"] for m in mapped] == [0, 0, 1]
    first = mapped[0]
    assert first["side"] == "long"
    assert first["signal_name"] == "strat_a"
    assert first["price"] == 10.5
    assert first["freq"] == "1d"
    assert first["reason"] == "r1"
    assert first["score"] == 0.87
    # score 为 None/NaN 时映射为 None
    assert mapped[1]["score"] is None
    assert mapped[2]["score"] == -0.5


def test_arrow_series_direction_and_stacking() -> None:
    mapped = map_signals_to_bars(_fake_prep(), _fake_signals())
    ohlc = [[10.0, 10.5, 9.8, 10.8], [11.0, 11.2, 10.9, 11.5]]
    series = _build_signal_arrow_series(mapped, ohlc)
    buy = next(s for s in series if s["name"] == "买入")
    sell = next(s for s in series if s["name"] == "卖出")
    # signal 列 BUY -> 买入（上箭头，low 下方，同 bar 堆叠偏移递增）
    assert [p["symbolOffset"] for p in buy["data"]] == [[0, 12], [0, 28]]
    assert buy["data"][0]["value"] == [0, 9.8]
    # signal 列 SELL -> 卖出（下箭头，high 上方）
    assert sell["data"][0]["value"] == [1, 11.5]
    assert sell["data"][0]["symbolOffset"] == [0, -12]


def test_map_signals_direction_prefers_signal_column() -> None:
    """箭头方向优先以 signal 列为准，即使 side 列与之相反。"""
    prep = _fake_prep()
    signals = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02"]),
        "signal_name": ["strat_x"],
        "side": ["long"],
        "signal": ["SELL"],
        "freq": ["1d"],
        "price": [10.0],
        "reason": ["r"],
        "score": [0.5],
    })
    mapped = map_signals_to_bars(prep, signals)
    assert mapped[0]["kind"] == "SELL"
    series = _build_signal_arrow_series(mapped, [[10, 10.2, 9.8, 10.5]])
    assert any(s["name"] == "卖出" for s in series)


def test_map_signals_filter_by_chart_freq() -> None:
    """提供 chart_freq 时只保留同周期信号。"""
    prep = _fake_prep()
    signals = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02", "2025-01-02", "2025-01-03"]),
        "signal_name": ["a", "a", "b"],
        "side": ["long", "long", "long"],
        "signal": ["BUY", "BUY", "SELL"],
        "freq": ["1d", "30m", "1d"],
        "price": [10.0, 10.0, 11.0],
        "reason": ["", "", ""],
        "score": [None, None, None],
    })
    mapped = map_signals_to_bars(prep, signals, chart_freq="1d")
    assert len(mapped) == 2
    assert set(m["freq"] for m in mapped) == {"1d"}


def test_chart_meta_signal_grouping() -> None:
    mapped = map_signals_to_bars(_fake_prep(), _fake_signals())
    meta = build_chart_meta(
        ["2025-01-02", "2025-01-03"],
        [[10.0, 10.5, 9.8, 10.8], [11.0, 11.2, 10.9, 11.5]],
        [],
        mapped,
    )
    sigs0 = meta["signals"][0]
    assert len(sigs0) == 2
    assert sigs0[0]["type"] == "BUY"
    assert sigs0[0]["strategy"] == "strat_a"
    assert sigs0[0]["strength"] == 0.87
    assert sigs0[1]["strength"] is None
    assert meta["signals"][1][0]["type"] == "SELL"
    assert meta["signals"][1][0]["strength"] == -0.5


# ---------- review-fix 回归测试 ----------


def test_extract_symbol_data_filters_by_exchange() -> None:
    df = pd.DataFrame({
        "exchange": ["as", "ths", "as"],
        "symbol": ["600519", "600519", "600519"],
        "end_ts": [1735689600000, 1735689600000, 1735689600000],
        "close": [100.0, 200.0, 100.0],
    })
    prep_as, _ = extract_symbol_data(df, "600519", exchange="as")
    prep_ths, _ = extract_symbol_data(df, "600519", exchange="ths")
    assert prep_as is not None
    assert prep_ths is not None
    assert len(prep_as) == 2
    assert len(prep_ths) == 1


def test_date_labels_include_time_for_intraday() -> None:
    s = pd.Series(pd.to_datetime(["2025-01-02 09:30", "2025-01-02 10:00"]))
    labels = date_labels(s)
    assert labels == ["2025-01-02 09:30", "2025-01-02 10:00"]


def test_date_labels_daily_freq_ignores_time() -> None:
    """日线/周线明确按日期展示，不受收盘时间戳影响。"""
    s = pd.Series(pd.to_datetime(["2025-01-02 15:00", "2025-01-03 15:00"]))
    assert date_labels(s, freq="1d") == ["2025-01-02", "2025-01-03"]
    assert date_labels(s, freq="1w") == ["2025-01-02", "2025-01-03"]


def test_date_labels_date_only_for_daily() -> None:
    s = pd.Series(pd.to_datetime(["2025-01-02", "2025-01-03"]))
    labels = date_labels(s)
    assert labels == ["2025-01-02", "2025-01-03"]


def test_map_signals_intraday_nearest_bar() -> None:
    prep = pd.DataFrame({
        "_x": pd.to_datetime(["2025-01-02 09:30", "2025-01-02 10:00", "2025-01-02 10:30"]),
    })
    signals = pd.DataFrame({
        "signal_date": pd.to_datetime(["2025-01-02 09:46"]),
        "signal_name": ["strat_a"],
        "side": ["long"],
        "signal": ["BUY"],
        "freq": ["30m"],
        "price": [10.0],
        "reason": ["r1"],
        "score": [0.5],
    })
    mapped = map_signals_to_bars(prep, signals)
    assert len(mapped) == 1
    assert mapped[0]["barIndex"] == 1  # nearest to 10:00


def test_build_echarts_html_escapes_script_tag() -> None:
    charts = [{
        "id": "ch_x",
        "height": 100,
        "option": {
            "title": {"text": "</script><script>alert(1)</script>"},
            "series": [],
            "xAxis": {},
            "yAxis": {},
        },
    }]
    metas = {"ch_x": {"dates": [], "kline": [], "mas": [], "signals": {}}}
    html = build_echarts_html(charts, metas)
    # The dangerous literal from the title must be escaped inside the option JSON.
    assert '"</script><script>alert(1)</script>"' not in html
    assert '"<\\/script><\\/script>"' in html or '"<\\/script><script>alert(1)<\\/script>"' in html


# ---------- 数值格式化 ----------


def test_to_echarts_ohlc_rounds_ge_one_to_two_decimals() -> None:
    """>=1 的 OHLC 保留两位小数；<1 保留原精度。"""
    prep = pd.DataFrame({
        "open": [1.23456, 0.12345],
        "close": [2.34567, 0.23456],
        "low": [1.11111, 0.11111],
        "high": [3.33333, 0.33333],
    })
    ohlc = to_echarts_ohlc(prep)
    assert ohlc[0] == [1.23, 2.35, 1.11, 3.33]
    assert ohlc[1] == [0.12345, 0.23456, 0.11111, 0.33333]


def test_to_echarts_volume_rounds_ge_one_to_two_decimals() -> None:
    """>=1 的成交量保留两位小数；<1 保留原精度。"""
    prep = pd.DataFrame({"volume": [1234.5678, 0.9876]})
    vol = to_echarts_volume(prep)
    assert vol[0] == 1234.57
    assert vol[1] == 0.9876
