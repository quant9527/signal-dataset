"""display_signals_compact 集成级别验证：每行 K 线链接生成逻辑。

聚焦关键场景：
- 多频信号下，普通 tab 链接应使用每组最新一条信号的 freq；
- link_freq 显式传入时使用该值（周期 tab 的语义）；
- 占位符 / 空值不会生成可用链接。
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pandas as pd

from symbol_picker import encode_symbol_token
from utils import build_kline_link_url, display_signals_compact


def _row_urls(
    df: pd.DataFrame,
    *,
    group_by_cols: list[str],
    include_freq: bool,
    link_freq: str | None,
) -> list[str]:
    """在 patch 后的环境中运行 display_signals_compact 并捕获渲染的 DataFrame。"""

    captured: dict[str, Any] = {}

    def _capture(data, *, column_config, **kwargs):
        captured["data"] = data.copy()
        captured["column_config"] = column_config
        return None

    with patch("streamlit.dataframe", side_effect=_capture):
        display_signals_compact(
            df,
            group_by_cols=group_by_cols,
            include_freq=include_freq,
            link_freq=link_freq,
        )
    return list(captured["data"]["_kline_url"])


def _df() -> pd.DataFrame:
    return pd.DataFrame({
        "exchange": ["as", "as", "as"],
        "symbol": ["000001", "000001", "000002"],
        "symbol_name": ["平安银行", "平安银行", "万科A"],
        "signal_name": ["a", "b", "a"],
        "signal_date": pd.to_datetime([
            "2025-01-05",
            "2025-01-10",
            "2025-01-08",
        ]),
        "freq": ["30m", "1d", "1h"],
        "price": [10.0, 11.0, 12.0],
        "score": [0.1, 0.2, 0.3],
    })


def test_default_tab_uses_latest_signal_freq_per_group() -> None:
    """Symbol 优先：同 symbol 出现多个 freq 时，每组链接使用该组最新信号 freq。"""
    df = _df()
    urls = _row_urls(
        df,
        group_by_cols=["exchange", "symbol"],
        include_freq=True,
        link_freq=None,
    )
    assert urls == [
        build_kline_link_url("as", "000001", "1d"),  # 最新 1d
        build_kline_link_url("as", "000002", "1h"),
    ]


def test_explicit_link_freq_overrides_per_row_freq() -> None:
    """周期 tab 显式传入 link_freq 时，统一使用传入值。"""
    df = _df()
    cap: dict[str, Any] = {}

    def _capture(data, *, column_config, **kwargs):
        cap["data"] = data.copy()

    with patch("streamlit.dataframe", side_effect=_capture):
        display_signals_compact(
            df,
            group_by_cols=["exchange", "symbol", "signal_name"],
            include_freq=False,
            link_freq="1d",
        )
    data = cap["data"]
    # 渲染后的 dataframe 已用 _display_symbol 合并 exchange+symbol；
    # 直接断言每行 _kline_url 与 _display_symbol 解析得到的 token 吻合且 freq=1d。
    for _, row in data.iterrows():
        display = str(row["_display_symbol"])
        ex_sym, _, _ = display.partition("-")
        ex, _, sym = ex_sym.partition(":")
        assert row["_kline_url"] == f"/kline?symbol={encode_symbol_token(ex, sym, '1d')}"
    assert len(data) == 3


def test_invalid_freq_falls_back_to_default() -> None:
    """freq 列存在但全部非法时，回退到默认 1d。"""
    df = pd.DataFrame({
        "exchange": ["as"],
        "symbol": ["000001"],
        "symbol_name": ["x"],
        "signal_name": ["a"],
        "signal_date": pd.to_datetime(["2025-01-01"]),
        "freq": ["bogus"],
    })
    urls = _row_urls(
        df,
        group_by_cols=["exchange", "symbol"],
        include_freq=True,
        link_freq=None,
    )
    assert urls == [build_kline_link_url("as", "000001", "1d")]


def test_placeholder_values_skip_kline_link() -> None:
    """`(No Exchange)` / `(No Symbol)` 占位符不会生成链接。"""
    df = pd.DataFrame({
        "exchange": ["", "as"],
        "symbol": ["000001", ""],
        "symbol_name": ["x", "y"],
        "signal_name": ["a", "a"],
        "signal_date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
    })
    cap: dict[str, Any] = {}

    def _capture(data, *, column_config, **kwargs):
        cap["data"] = data.copy()

    with patch("streamlit.dataframe", side_effect=_capture):
        display_signals_compact(
            df,
            group_by_cols=["exchange", "symbol"],
            include_freq=True,
            link_freq=None,
        )
    urls = list(cap["data"]["_kline_url"])
    assert urls == ["", ""]
    # 全部都是空 URL → 不应启用 LinkColumn
    assert cap.get("column_config") is None or "_kline_url" not in cap["column_config"]


def test_link_config_present_when_any_url_valid() -> None:
    """只要存在一行有效 URL，就启用 LinkColumn 配置。"""
    df = _df()
    captured: dict[str, Any] = {}

    def _capture(data, *, column_config, **kwargs):
        captured["data"] = data.copy()
        captured["column_config"] = column_config

    with patch("streamlit.dataframe", side_effect=_capture):
        display_signals_compact(
            df,
            group_by_cols=["exchange", "symbol"],
            include_freq=True,
            link_freq=None,
        )
    assert "_kline_url" in captured["column_config"]
    cfg = captured["column_config"]["_kline_url"]
    # Streamlit 1.59 的 LinkColumn 字段：label/width/help/...，display_text 嵌套在 type_config 中
    assert cfg.get("help", "").startswith("打开对应 K 线页")
    type_cfg = cfg.get("type_config", {})
    assert type_cfg.get("display_text") == "K线 →"
    assert type_cfg.get("type") == "link"
    assert captured["data"]["_kline_url"].iloc[0].startswith("/kline?symbol=")


def test_url_token_matches_encode_symbol_token() -> None:
    """URL 中 token 部分必须与 encode_symbol_token 完全一致。"""
    url = build_kline_link_url("as", "000001", "1d")
    assert url == f"/kline?symbol={encode_symbol_token('as', '000001', '1d')}"
