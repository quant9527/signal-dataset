"""Regression test: K 线页 freq→aggregate 映射 + 服务端完全没数据时的 fallback。

背景：
- 用户报告 `?symbol=asindex:sh000131:1w&...` 页面报错"拉取失败..."。
- 根因：Flight 服务端不直接入库 1w 数据。按 quant-lab `lab/data.py:296-297` 的做法，
  1w 应当传 tag=`asindex_sh000131_1d`（基础频）+ 请求体 `kline_aggregate="1w"`，
  让服务端把 1d 数据聚合成 1w 返回。
- 修复（`_fetch_groups`）：freq 属于派生集（`1w`/`1M`）时，tag 用 `1d`，
  `kline_aggregate` 传 `freq`。其他 freq 保持原样。
- 兜底：当服务端聚合也失败（连 1d 基础数据都没有），按 `_FREQ_FALLBACK`
  链逐个降级，并静默回写 URL。
"""
from __future__ import annotations

import os
import tempfile

import pandas as pd


def _run_page_with_mock_fetch(allow_aggregates, allow_bases):
    """构造一个最小可执行的 mock script，跑 page_kline_fullscreen，返回 AppTest 结果。

    allow_aggregates: 允许通过的 aggregate 集合（支持 "1w", "1M", "1d" 或 ""）
    allow_bases: 允许通过的 tag 后缀集合（"1d"）
    """
    aggregates_repr = repr(list(allow_aggregates))
    bases_repr = repr(list(allow_bases))
    script = f'''
import sys
sys.path.insert(0, "/home/lei/repo/signalview")
import pandas as pd
import streamlit
class _FakeQP:
    def __init__(self):
        self._d = {{"symbol": "asindex:sh000131:1w", "start": "2026-07-03", "end": "2026-07-31"}}
    def __contains__(self, k): return k in self._d
    def get(self, k, default=None):
        v = self._d.get(k, default)
        if isinstance(v, list): return v[0] if v else ""
        return v
    def __setitem__(self, k, v): self._d[k] = v
    def __delitem__(self, k): del self._d[k]
    def to_dict(self): return dict(self._d)
streamlit.query_params = _FakeQP()

import streamlit.components.v1 as scv1
scv1.html = lambda *a, **kw: None

import flight_kline_client as fkc

_ALLOWED_AGG = set({aggregates_repr})
_ALLOWED_BASES = set({bases_repr})

def fake_fetch(tags, start_ms, end_ms, flight_url=None, *, kline_reverse=False, kline_aggregate=""):
    if tags is None or not tags: return None
    if kline_aggregate not in _ALLOWED_AGG: return None
    if not any(any("_" + b in t for b in _ALLOWED_BASES) for t in tags): return None
    days = pd.date_range("2026-07-01", periods=20, freq="D", tz="UTC")
    return pd.DataFrame({{
        "exchange": ["asindex"]*20,
        "symbol": ["sh000131"]*20,
        "end_ts": [int(t.timestamp()*1000) for t in days],
        "open": [3000.0]*20, "high": [3050.0]*20, "low": [2980.0]*20, "close": [3030.0]*20,
        "vol": [1e9]*20,
        "ma5": [3000.0]*20, "ma10": [3000.0]*20,
        "macd": [0.0]*20, "dif": [0.0]*20, "dea": [0.0]*20,
    }})
fkc.fetch_kline_dataframe = fake_fetch

import data as d
d.get_kline_signals = lambda *a, **kw: pd.DataFrame(columns=["signal_date","signal_name","side","signal","freq","price","reason","score"])

from app_pages import kline_fullscreen as kfs
kfs._build_symbol_name_map = lambda exchanges_symbols: {{("asindex","sh000131"): "上证高新"}}
kfs._build_preset_name_map = lambda presets: {{(ex,sym): f"{{ex}}:{{sym}}" for ex,sym in presets}}

from app_pages.kline_fullscreen import page_kline_fullscreen
page_kline_fullscreen()
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/home/lei/repo/signalview") as f:
        f.write(script)
        path = f.name
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(path, default_timeout=30)
        at.run()
        return at
    finally:
        os.unlink(path)


def test_1w_request_uses_1d_tag_with_aggregate():
    """1w 请求应当被转换为 1d tag + aggregate='1w'，无需 fallback。"""
    at = _run_page_with_mock_fetch(allow_aggregates={"1w", ""}, allow_bases={"1d"})
    assert not list(at.exception), f"got exception: {[x.message for x in at.exception]}"
    assert not list(at.error), f"got error: {[e.value for e in at.error]}"
    info_msgs = [i.value for i in at.info]
    # 不应触发 fallback 提示
    assert not any("降级到" in m for m in info_msgs), (
        f"1w 请求不应触发 fallback；got {info_msgs}"
    )


def test_no_data_anywhere_shows_flight_error():
    """服务端连 1d 基础数据都没有 → 显示 Flight 错误。"""
    at = _run_page_with_mock_fetch(allow_aggregates=set(), allow_bases=set())
    assert not list(at.exception)
    err_msgs = [e.value for e in at.error]
    assert any("Flight" in m or "pyarrow" in m for m in err_msgs), f"got: {err_msgs}"