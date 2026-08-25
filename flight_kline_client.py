"""
quant-lab Flight K 线 RPC（无 Streamlit 依赖）。
供 data.py（最新价）与 signalml（批量历史 K 线）共用，避免重复实现。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Any

import pandas as pd


def default_flight_url() -> str:
    return os.environ.get("FLIGHT_URL", "grpc://127.0.0.1:50001")


# 指数 K 线与 A 股个股 tag 不同：如沪深300 为 asindex_sh000300_1d，而非 as_000300_1d
EXCHANGE_ASINDEX = "asindex"
SYMBOL_CSI300 = "sh000300"


def _norm_symbol_6(s: str) -> str:
    s = str(s).strip()
    s = re.sub(r"\.[A-Za-z]+$", "", s)
    s = re.sub(r"^[sS][hH]|^[sS][zZ]", "", s)
    return s.zfill(6) if s else ""


def normalize_asindex_symbol(s: str) -> str:
    """公开：指数代码规范化，如 sh000300（与 build_kline_tags / 缓存 key 一致）。"""
    return _norm_asindex_symbol(s)


def _norm_asindex_symbol(s: str) -> str:
    """Flight tag 中段：如 sh000300、sz399001（须带 sh/sz 前缀）。"""
    s = str(s).strip().lower().replace(" ", "")
    s = re.sub(r"\.[A-Za-z]+$", "", s)
    if re.fullmatch(r"sh\d{6}", s) or re.fullmatch(r"sz\d{6}", s):
        return s
    if re.fullmatch(r"\d{6}", s):
        return f"sh{s}"
    return ""


def build_kline_tags(symbols: list[str], exchange: str, kline_freq: str = "1d") -> list[str]:
    """
    生成 Flight tags：{exchange}_{symbol}_{freq}。
    - exchange=as：个股 6 位代码，如 as_600519_1d
    - exchange=ths：同个股 6 位规范，如 ths_600519_1d
    - exchange=asindex：指数带 sh/sz，如 asindex_sh000300_1d（沪深300）
    - exchange=hyperliquid：crypto pair，如 hyperliquid_BTC_1d、hyperliquid_BTC-USDT_1d
    """
    ex = str(exchange).strip() or "as"
    fq = str(kline_freq).strip() or "1d"
    if ex.lower() == EXCHANGE_ASINDEX:
        tags: list[str] = []
        for raw in symbols:
            sym = _norm_asindex_symbol(raw)
            if sym:
                tags.append(f"{EXCHANGE_ASINDEX}_{sym}_{fq}")
        return tags
    if ex.lower() == "hyperliquid":
        tags = []
        for raw in symbols:
            sym = str(raw).strip().upper()
            if sym:
                tags.append(f"hyperliquid_{sym}_{fq}")
        return tags
    codes = [_norm_symbol_6(s) for s in symbols]
    codes = [c for c in codes if c.isdigit() and len(c) == 6]
    return [f"{ex}_{c}_{fq}" for c in codes]


def fetch_kline_dataframe(
    tags: list[str],
    start_time_ms: int,
    end_time_ms: int,
    flight_url: str | None = None,
    *,
    kline_reverse: bool = False,
    kline_aggregate: str = "",
) -> pd.DataFrame | None:
    """
    单次 do_get，返回 Flight 完整 K 线表（多标的混表）。
    请求体与 quant-lab / signalview data._get_latest_market_flight 一致。
    kline_reverse：与 quant-lab 一致，控制服务端是否对 K 线做镜像反转处理。
    kline_aggregate：与 quant-lab `do_get_kline` 一致。派生周期（`1w` / `1M`）
        服务端不直接入库，需要传原始 `1d` 数据 + `aggregate="1w"`，由服务端做
        周期聚合。signalview 调用方应当：
        - 若 entry.freq 是派生频率，把 tag 后缀改为 `"1d"`；
        - 把 entry.freq 作为 `kline_aggregate` 一并传入；
        （kline_fullscreen._fetch_groups 内部统一处理这一映射）
    """
    if not tags:
        return None
    try:
        from pyarrow import flight
    except ImportError:
        return None
    url = flight_url or default_flight_url()
    req: dict[str, Any] = {
        "name": "kline",
        "start_time": int(start_time_ms),
        "end_time": int(end_time_ms),
        "tags": tags,
        "kline_aggregate": kline_aggregate,
        "kline_reverse": bool(kline_reverse),
    }
    try:
        client = flight.FlightClient(url)
        ticket = flight.Ticket(json.dumps(req))
        reader = client.do_get(ticket)
        kline_df = reader.read_pandas()
    except Exception as e:
        print(f"[Flight] kline request failed: {e}")
        return None
    if kline_df is None or kline_df.empty:
        return None
    return kline_df


def _timestamp_series_to_date(s: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_datetime(s, unit="ms", errors="coerce").dt.normalize()
    return pd.to_datetime(s, errors="coerce").dt.normalize()


def normalize_kline_group_to_bars(group: pd.DataFrame) -> pd.DataFrame:
    """单标的子表 -> trade_date, close + Flight 返回的数值因子列（列名小写）。"""
    if group.empty:
        return pd.DataFrame(columns=["trade_date", "close"])
    df = group.copy()
    ts_col = "end_ts" if "end_ts" in df.columns else "timestamp" if "timestamp" in df.columns else None
    if ts_col is None and "datetime" in df.columns:
        ts_col = "datetime"
    if ts_col is None:
        return pd.DataFrame(columns=["trade_date", "close"])
    close_col = "close" if "close" in df.columns else "Close" if "Close" in df.columns else None
    if close_col is None:
        return pd.DataFrame(columns=["trade_date", "close"])
    df = df.sort_values(ts_col)
    out = pd.DataFrame(
        {
            "trade_date": _timestamp_series_to_date(df[ts_col]),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
        }
    )
    skip_lower = {
        str(ts_col).lower(),
        str(close_col).lower(),
        "exchange",
        "symbol",
        "open",
        "high",
        "low",
        "volume",
        "amount",
    }
    seen: set[str] = {"trade_date", "close"}
    for c in df.columns:
        lc = str(c).strip().lower()
        if lc in skip_lower or lc in seen:
            continue
        if lc in ("open", "high", "low", "volume", "amount"):
            continue
        num = pd.to_numeric(df[c], errors="coerce")
        if num.notna().sum() == 0:
            continue
        out[lc] = num
        seen.add(lc)
    out = out.dropna(subset=["trade_date", "close"]).sort_values("trade_date")
    out = out.drop_duplicates(subset=["trade_date"], keep="last")
    return out.reset_index(drop=True)


def _bars_key_from_flight_symbol(sym: str) -> str | None:
    """与 build_kline_tags 侧 symbol 对齐：sh000300 或 6 位个股码。"""
    s = str(sym).strip().lower()
    if re.fullmatch(r"sh\d{6}", s) or re.fullmatch(r"sz\d{6}", s):
        return s
    code = _norm_symbol_6(sym)
    if code.isdigit() and len(code) == 6:
        return code
    return None


def split_kline_by_symbol(kline_df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if kline_df.empty or "symbol" not in kline_df.columns:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for sym, g in kline_df.groupby("symbol", sort=False):
        key = _bars_key_from_flight_symbol(str(sym))
        if not key:
            continue
        out[key] = normalize_kline_group_to_bars(g)
    return out


def fetch_klines_by_symbols_flight(
    symbols: list[str],
    *,
    exchange: str = "as",
    kline_freq: str = "1d",
    lookback_years: int = 15,
    flight_url: str | None = None,
    kline_reverse: bool = False,
) -> dict[str, pd.DataFrame] | None:
    tags = build_kline_tags(symbols, exchange, kline_freq)
    if not tags:
        return None
    end_ms = int(datetime.now().timestamp() * 1000)
    start_ms = int((datetime.now() - timedelta(days=365 * lookback_years)).timestamp() * 1000)
    raw = fetch_kline_dataframe(
        tags, start_ms, end_ms, flight_url=flight_url, kline_reverse=kline_reverse
    )
    if raw is None or raw.empty:
        return None
    return split_kline_by_symbol(raw)
