"""
K 线图表渲染（Kline.html 视觉风格）。

- 深色卡片式图表面板、固定位置 tooltip、箭头 BUY/SELL 信号标记（同 bar 同方向堆叠）
- 保留分析特性：MA 均线、成交量、MACD 子图、多标的归一化走势对比 + ECharts connect 联动
- 数据来自 Flight（同一次 do_get）：OHLC、volume、ma5/ma10/…、MACD(DIF/DEA/hist)
"""

from __future__ import annotations

import json
import re
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import flight_kline_client as fkc

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 均线颜色
MA_COLORS = ["#ffeb3b", "#29b6f6", "#ab47bc", "#66bb6a", "#ffa726", "#ec407a"]


def _fmt_price(v: float) -> float:
    """价格类数值格式化：>=1 保留两位小数，<1 保留原精度。"""
    if pd.isna(v):
        return float("nan")
    fv = float(v)
    return round(fv, 2) if fv >= 1 else fv

# Kline.html 调色板
UP_COLOR = "#26a69a"
DOWN_COLOR = "#ef5350"
BORDER_COLOR = "#2b333d"
MUTED_COLOR = "#8b949e"
SPLIT_COLOR = "#1c232b"

# 箭头图标（SVG path）
ARROW_UP = "path://M512 128 L864 640 L608 640 L608 896 L416 896 L416 640 L160 640 Z"
ARROW_DOWN = "path://M512 896 L160 384 L416 384 L416 128 L608 128 L608 384 L864 384 Z"


# ===========================================================
# Flight / 数据帧解析
# ===========================================================


def resolve_flight_url() -> str:
    try:
        sec = st.secrets
        if "FLIGHT_URL" in sec:
            u = sec["FLIGHT_URL"]
            if u is not None and str(u).strip():
                return str(u).strip()
        if "flight" in sec:
            block = sec["flight"]
            if isinstance(block, dict) and block.get("url"):
                u = str(block["url"]).strip()
                if u:
                    return u
    except (FileNotFoundError, KeyError, TypeError, RuntimeError):
        pass
    return fkc.default_flight_url()


def symbol_key_from_tags(tags: list[str]) -> str | None:
    if not tags:
        return None
    parts = tags[0].split("_")
    if len(parts) < 3:
        return None
    return parts[1].lower()


def _col(df: pd.DataFrame, name: str) -> str | None:
    """Return *name* if it exists in *df*, else None."""
    return name if name in df.columns else None


def _find_ma_columns(df: pd.DataFrame) -> list[str]:
    """Flight schema: ma5, ma10, ma20, ma60, ma120, ma250."""
    found: list[tuple[int, str]] = []
    for c in df.columns:
        lc = str(c).strip().lower()
        m = re.fullmatch(r"ma(\d+)", lc)
        if m:
            found.append((int(m.group(1)), c))
    found.sort(key=lambda x: x[0])
    return [c for _, c in found]


def _find_macd_columns(df: pd.DataFrame) -> dict[str, str]:
    """Flight schema: macd (histogram), dif, dea."""
    lm = {str(c).lower().strip(): c for c in df.columns}
    roles: dict[str, str] = {}
    if "macd" in lm and "dif" in lm and "dea" in lm:
        roles["hist"] = lm["macd"]
        roles["dif"] = lm["dif"]
        roles["dea"] = lm["dea"]
        return roles
    # Fallback: TA-Lib style naming (non-Flight data sources)
    if "macd" in lm and "macdsignal" in lm:
        roles["dif"] = lm["macd"]
        roles["dea"] = lm["macdsignal"]
        if "macdhist" in lm:
            roles["hist"] = lm["macdhist"]
        return roles
    return roles


def _prepare_kline_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict] | None:
    """解析时间、OHLC、成交量、均线、MACD；返回排序后的表与元信息。"""
    if df.empty:
        return None
    ts_col = _col(df, "end_ts") or _col(df, "timestamp")
    if ts_col is None:
        return None
    o = _col(df, "open")
    h = _col(df, "high")
    lo = _col(df, "low")
    c = _col(df, "close")
    if c is None:
        return None

    out = df.copy()
    ts_raw = out[ts_col]
    out["_x"] = pd.to_datetime(ts_raw, unit="ms", errors="coerce", utc=True)
    if out["_x"].isna().all():
        out["_x"] = pd.to_datetime(ts_raw, errors="coerce", utc=True)
    out["_x"] = out["_x"].dt.tz_convert(TZ_SHANGHAI).dt.tz_localize(None)

    for name, col in (("open", o), ("high", h), ("low", lo), ("close", c)):
        if col is None:
            if name == "close":
                return None
            continue
        out[name] = pd.to_numeric(out[col], errors="coerce")
    if "open" not in out.columns:
        out["open"] = out["close"]
    if "high" not in out.columns:
        out["high"] = out["close"]
    if "low" not in out.columns:
        out["low"] = out["close"]

    vol_src = _col(out, "vol")
    has_volume = vol_src is not None
    if has_volume:
        out["volume"] = pd.to_numeric(out[vol_src], errors="coerce")

    ma_src_cols = _find_ma_columns(df)
    ma_plot: list[str] = []
    for col in ma_src_cols:
        lc = str(col).strip().lower()
        out[lc] = pd.to_numeric(out[col], errors="coerce")
        ma_plot.append(lc)

    macd_src = _find_macd_columns(df)
    macd_plot: dict[str, str] = {}
    for role, src in macd_src.items():
        key = f"_macd_{role}"
        out[key] = pd.to_numeric(out[src], errors="coerce")
        macd_plot[role] = key

    has_pct_change = "pct_change" in out.columns
    if has_pct_change:
        out["pct_change"] = pd.to_numeric(out["pct_change"], errors="coerce")

    out = out.dropna(subset=["_x", "close"]).sort_values("_x")

    meta = {
        "has_volume": has_volume,
        "ma_cols": ma_plot,
        "macd": macd_plot,
        "has_pct_change": has_pct_change,
    }
    return out, meta


def extract_symbol_data(
    df: pd.DataFrame,
    sym_key: str,
    exchange: str | None = None,
) -> tuple[pd.DataFrame, dict] | None:
    """从混表中按 exchange + symbol 过滤并解析 K 线。"""
    raw = df.copy()
    sym_lower = sym_key.lower()
    if "symbol" in raw.columns:
        raw = raw[raw["symbol"].astype(str).str.lower() == sym_lower]
    if exchange is not None and "exchange" in raw.columns:
        raw = raw[raw["exchange"].astype(str).str.lower() == exchange.lower()]
    if raw.empty:
        return None
    return _prepare_kline_frame(raw)


# ===========================================================
# ECharts 数据转换
# ===========================================================


def date_labels(s: pd.Series, freq: str | None = None) -> list[str]:
    """ECharts 横轴分类标签（东八区墙钟）。日线/周线只显示日期，日内线额外显示时分。"""
    dt = pd.to_datetime(s)
    # 明确日线/周线：即使底层时间戳带收盘时间，也只展示日期
    if freq in ("1d", "1w"):
        return dt.dt.strftime("%Y-%m-%d").tolist()
    has_time = (dt.dt.hour != 0).any() | (dt.dt.minute != 0).any()
    fmt = "%Y-%m-%d %H:%M" if has_time else "%Y-%m-%d"
    return dt.dt.strftime(fmt).tolist()


def to_echarts_ohlc(prep: pd.DataFrame) -> list[list[float]]:
    """ECharts candlestick 数据，[open, close, low, high] 格式。"""
    rows: list[list[float]] = []
    for _, r in prep.iterrows():
        rows.append([
            _fmt_price(r["open"]),
            _fmt_price(r["close"]),
            _fmt_price(r["low"]),
            _fmt_price(r["high"]),
        ])
    return rows


def to_echarts_volume(prep: pd.DataFrame) -> list[float | None]:
    if "volume" not in prep.columns:
        return []
    return [None if pd.isna(v) else _fmt_price(v) for v in prep["volume"]]


def to_echarts_ma(prep: pd.DataFrame, ma_cols: list[str]) -> list[dict[str, Any]]:
    lines: list[dict] = []
    for i, lc in enumerate(ma_cols):
        if lc not in prep.columns:
            continue
        s = prep[lc]
        if s.notna().sum() == 0:
            continue
        lines.append(
            {
                "name": lc.upper(),
                "data": [None if pd.isna(v) else round(float(v), 4) for v in s],
                "color": MA_COLORS[i % len(MA_COLORS)],
            }
        )
    return lines


def to_echarts_macd(prep: pd.DataFrame, macd_keys: dict[str, str]) -> dict[str, list[float | None]] | None:
    if not macd_keys:
        return None
    out: dict[str, list[float | None]] = {}
    for role, col in macd_keys.items():
        if col not in prep.columns:
            out[role] = []
        else:
            out[role] = [None if pd.isna(v) else round(float(v), 6) for v in prep[col]]
    return out


# ===========================================================
# 信号映射与标记
# ===========================================================


def map_signals_to_bars(
    prep: pd.DataFrame,
    signals_df: pd.DataFrame,
    chart_freq: str | None = None,
) -> list[dict]:
    """将信号按 signal_date 匹配到 K 线 bar 索引。

    - 若提供 chart_freq，只保留 freq 列与之匹配的信号，避免跨周期堆叠。
    - 箭头方向优先以 signal 列（BUY/SELL）为准，side 列仅作兜底。
    - 同一 bar 同一方向同一策略仅保留一条，防止重复箭头。
    """
    if signals_df.empty:
        return []
    if chart_freq is not None and "freq" in signals_df.columns:
        signals_df = signals_df[signals_df["freq"].astype(str) == chart_freq]

    bar_dates = prep["_x"].tolist()
    is_intraday = any(
        d.hour != 0 or d.minute != 0 or d.second != 0 for d in bar_dates
    )
    result: list[dict] = []
    seen: set[tuple[int, str, str]] = set()
    for _, sig in signals_df.iterrows():
        sig_dt = sig["signal_date"]
        matched_idx = None
        if is_intraday:
            # 日内周期：找时间戳最近的 bar
            best_delta = None
            for i, bdt in enumerate(bar_dates):
                delta = abs((bdt - sig_dt).total_seconds())
                if best_delta is None or delta < best_delta:
                    best_delta = delta
                    matched_idx = i
        else:
            # 日线/周线：按日期部分匹配
            for i, bdt in enumerate(bar_dates):
                if bdt.date() == sig_dt.date():
                    matched_idx = i
                    break
        if matched_idx is None:
            continue

        signal_val = str(sig.get("signal", "")).strip().upper()
        side_val = str(sig.get("side", "")).strip().lower()
        if signal_val == "BUY":
            kind = "BUY"
        elif signal_val == "SELL":
            kind = "SELL"
        else:
            kind = "BUY" if side_val == "long" else "SELL"

        key = (matched_idx, kind, str(sig.get("signal_name", "")))
        if key in seen:
            continue
        seen.add(key)

        score = sig.get("score")
        result.append({
            "barIndex": matched_idx,
            "kind": kind,
            "side": str(sig.get("side", "")),
            "signal": str(sig.get("signal", "")),
            "signal_name": str(sig.get("signal_name", "")),
            "freq": str(sig.get("freq", "")),
            "price": float(sig["price"]) if pd.notna(sig.get("price")) else None,
            "score": round(float(score), 2) if score is not None and pd.notna(score) else None,
            "reason": str(sig.get("reason", ""))[:120] if pd.notna(sig.get("reason")) else "",
        })
    return result


def _build_signal_arrow_series(
    signals: list[dict], ohlc: list[list[float]]
) -> list[dict]:
    """箭头 BUY/SELL scatter 系列；同一 bar 同一方向的多条信号按像素偏移堆叠。"""
    if not signals:
        return []
    stack_count: dict[tuple[int, str], int] = {}
    buy_pts: list[dict] = []
    sell_pts: list[dict] = []
    for sig in signals:
        idx = sig["barIndex"]
        if idx < 0 or idx >= len(ohlc):
            continue
        row = ohlc[idx]
        low, high = row[2], row[3]
        kind = sig.get("kind")
        if kind not in ("BUY", "SELL"):
            kind = "BUY" if sig.get("side") == "long" else "SELL"
        key = (idx, kind)
        n = stack_count.get(key, 0)
        stack_count[key] = n + 1
        if kind == "BUY":
            buy_pts.append({"value": [idx, round(low, 2)], "symbolOffset": [0, 12 + n * 16]})
        else:
            sell_pts.append({"value": [idx, round(high, 2)], "symbolOffset": [0, -12 - n * 16]})

    series: list[dict] = []
    if buy_pts:
        series.append({
            "name": "买入",
            "type": "scatter",
            "data": buy_pts,
            "symbol": ARROW_UP,
            "symbolSize": 16,
            "itemStyle": {"color": UP_COLOR},
            "tooltip": {"show": False},
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 10,
        })
    if sell_pts:
        series.append({
            "name": "卖出",
            "type": "scatter",
            "data": sell_pts,
            "symbol": ARROW_DOWN,
            "symbolSize": 16,
            "itemStyle": {"color": DOWN_COLOR},
            "tooltip": {"show": False},
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "z": 10,
        })
    return series


def build_chart_meta(
    labels: list[str],
    ohlc: list[list[float]],
    ma_lines: list[dict[str, Any]],
    signals: list[dict],
    pct_change: list[float | None] | None = None,
) -> dict:
    """固定 tooltip 所需的每图数据：日期、K 线、均线、按 bar 聚合的信号、涨跌幅。"""
    sig_by_idx: dict[int, list[dict]] = {}
    for sig in signals:
        kind = sig.get("kind")
        if kind not in ("BUY", "SELL"):
            kind = "BUY" if sig.get("side") == "long" else "SELL"
        sig_by_idx.setdefault(sig["barIndex"], []).append({
            "type": kind,
            "strategy": sig["signal_name"],
            "price": str(round(sig["price"], 2)) if sig["price"] is not None else "-",
            "freq": sig["freq"],
            "strength": sig["score"],
            "reason": sig["reason"],
        })
    meta: dict[str, Any] = {
        "dates": labels,
        "kline": ohlc,
        "mas": ma_lines,
        "signals": sig_by_idx,
    }
    if pct_change is not None:
        meta["pct_change"] = pct_change
    return meta


# ===========================================================
# ECharts option 构建
# ===========================================================


def _kline_grids(has_volume: bool, has_macd: bool, total_height: int) -> list[dict]:
    """K 线 / 成交量 / MACD 子图布局，按 total_height 动态分配比例。

    顶部预留 40px 给标题，底部预留 20px，剩余空间按比例划分，
    避免小高度下图表子图重叠。
    """
    top = 40
    bottom = 20
    usable = max(100, total_height - top - bottom)

    if has_volume and has_macd:
        kline_h = int(usable * 0.55)
        vol_h = int(usable * 0.15)
        macd_top = top + kline_h + vol_h
        return [
            {"left": 60, "right": 20, "top": top, "height": kline_h},
            {"left": 60, "right": 20, "top": top + kline_h, "height": vol_h},
            {"left": 60, "right": 20, "top": macd_top, "bottom": bottom},
        ]
    if has_volume or has_macd:
        kline_h = int(usable * 0.70)
        return [
            {"left": 60, "right": 20, "top": top, "height": kline_h},
            {"left": 60, "right": 20, "top": top + kline_h, "bottom": bottom},
        ]
    return [{"left": 60, "right": 20, "top": top, "bottom": bottom}]


def _grid_axes(n_grids: int, labels: list[str]) -> tuple[list[dict], list[dict]]:
    x_axes: list[dict] = []
    y_axes: list[dict] = []
    for i in range(n_grids):
        x_axes.append({
            "type": "category",
            "data": labels,
            "gridIndex": i,
            "boundaryGap": True,
            "axisLine": {"lineStyle": {"color": BORDER_COLOR}},
            "axisLabel": {"show": i == 0, "color": MUTED_COLOR},
            "axisTick": {"show": i == 0},
            "splitLine": {"show": False},
            "min": "dataMin",
            "max": "dataMax",
        })
        y_axes.append({
            "type": "value",
            "gridIndex": i,
            "scale": True,
            "axisLine": {"lineStyle": {"color": BORDER_COLOR}},
            "axisLabel": {"color": MUTED_COLOR},
            "splitLine": {"lineStyle": {"color": SPLIT_COLOR}},
        })
    return x_axes, y_axes


def _macd_series(
    macd: dict[str, list[float | None]], grid_idx: int
) -> list[dict]:
    hist = macd.get("hist", [])
    bar_data: list[dict] = []
    for v in hist:
        if v is None:
            bar_data.append({"value": None, "itemStyle": {"color": "#555"}})
        else:
            bar_data.append({
                "value": v,
                "itemStyle": {"color": UP_COLOR if v >= 0 else DOWN_COLOR},
            })
    return [
        {
            "type": "bar",
            "name": "MACD",
            "data": bar_data,
            "xAxisIndex": grid_idx,
            "yAxisIndex": grid_idx,
        },
        {
            "type": "line",
            "name": "DIF",
            "data": macd.get("dif", []),
            "xAxisIndex": grid_idx,
            "yAxisIndex": grid_idx,
            "symbol": "none",
            "lineStyle": {"width": 1.5, "color": "#ffeb3b"},
        },
        {
            "type": "line",
            "name": "DEA",
            "data": macd.get("dea", []),
            "xAxisIndex": grid_idx,
            "yAxisIndex": grid_idx,
            "symbol": "none",
            "lineStyle": {"width": 1.5, "color": "#29b6f6"},
        },
    ]


def build_symbol_candle_option(
    title: str,
    labels: list[str],
    ohlc: list[list[float]],
    volume: list[float | None],
    ma_lines: list[dict[str, Any]],
    macd: dict[str, list[float | None]] | None,
    has_volume: bool,
    signals: list[dict] | None = None,
    height: int = 600,
) -> dict:
    """单个标的的 K 线 + 成交量 + MACD + 信号箭头（Kline.html 风格）。"""
    has_macd = macd is not None
    grids = _kline_grids(has_volume, has_macd, height)
    n_grids = len(grids)
    x_axes, y_axes = _grid_axes(n_grids, labels)

    if has_volume:
        y_axes[1]["axisLabel"]["formatter"] = "KLINE_VOL_FORMATTER"

    # 价格 Y 轴：>=1 保留两位小数，避免长尾浮点
    y_axes[0]["axisLabel"]["formatter"] = "KLINE_PRICE_FORMATTER"

    series: list[dict] = [
        {
            "name": "K线",
            "type": "candlestick",
            "data": ohlc,
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "itemStyle": {
                "color": UP_COLOR,
                "color0": DOWN_COLOR,
                "borderColor": UP_COLOR,
                "borderColor0": DOWN_COLOR,
            },
        }
    ]
    for ma in ma_lines:
        series.append({
            "type": "line",
            "name": ma["name"],
            "data": ma["data"],
            "xAxisIndex": 0,
            "yAxisIndex": 0,
            "symbol": "none",
            "lineStyle": {"width": 1.2, "color": ma["color"]},
        })

    if has_volume:
        vol_idx = 1
        bar_data: list[dict] = []
        for i in range(len(ohlc)):
            v = volume[i] if i < len(volume) else None
            if v is None:
                bar_data.append({"value": None, "itemStyle": {"color": "#555"}})
            else:
                up = ohlc[i][1] >= ohlc[i][0]
                color = "rgba(38,166,154,.5)" if up else "rgba(239,83,80,.5)"
                bar_data.append({"value": v, "itemStyle": {"color": color}})
        series.append({
            "type": "bar",
            "name": "成交量",
            "data": bar_data,
            "xAxisIndex": vol_idx,
            "yAxisIndex": vol_idx,
        })

    if has_macd and macd is not None:
        mi = 2 if has_volume else 1
        series.extend(_macd_series(macd, mi))

    series.extend(_build_signal_arrow_series(signals or [], ohlc))

    legend_names = ["K线"] + [m["name"] for m in ma_lines]
    if has_volume:
        legend_names.append("成交量")
    if has_macd:
        legend_names.extend(["MACD", "DIF", "DEA"])
    if signals:
        legend_names.extend(["买入", "卖出"])

    return {
        "animation": False,
        "title": {
            "text": title,
            "left": 12,
            "top": 6,
            "textStyle": {"color": "#e6edf3", "fontSize": 14, "fontWeight": 600},
        },
        "tooltip": {
            "trigger": "axis",
            "triggerOn": "mousemove",
            "axisPointer": {
                "type": "cross",
                "link": [{"xAxisIndex": "all"}],
                "label": {"backgroundColor": "#3b4754"},
            },
            "backgroundColor": "rgba(22,27,34,0.95)",
            "borderColor": BORDER_COLOR,
            "borderWidth": 1,
            "padding": [4, 10],
            "textStyle": {"color": "#c9d1d9", "fontSize": 12},
            "position": "KLINE_TIP_POS",
            "formatter": "KLINE_AXIS_TIP",
        },
        "axisPointer": {"link": [{"xAxisIndex": "all"}]},
        "legend": {
            "data": legend_names,
            "top": 6,
            "right": 20,
            "textStyle": {"color": MUTED_COLOR},
        },
        "grid": grids,
        "xAxis": x_axes,
        "yAxis": y_axes,
        "series": series,
        "dataZoom": [
            {"type": "inside", "xAxisIndex": list(range(n_grids)), "start": 55, "end": 100},
            {
                "type": "slider",
                "xAxisIndex": list(range(n_grids)),
                "height": 16,
                "bottom": 4,
                "borderColor": BORDER_COLOR,
                "textStyle": {"color": MUTED_COLOR},
                "start": 55,
                "end": 100,
            },
        ],
        "backgroundColor": "transparent",
    }


# ===========================================================
# HTML 组装（Kline.html 风格外壳 + 多图联动）
# ===========================================================

_TIP_JS = """
var UP='#26a69a', DOWN='#ef5350', BORDER='#2b333d', MUTED='#8b949e';
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function klineAxisTip(params, meta){
    var p=null, i;
    for(i=0;i<params.length;i++){ if(params[i].seriesType==='candlestick'){ p=params[i]; break; } }
    if(!p) p=params[0];
    var di=p.dataIndex;
    var k=meta.kline[di];
    var sep=' <span style="color:'+BORDER+'">|</span> ';
    var head=['<b>'+esc(meta.dates[di])+'</b>'];
    if(k){
        var c=k[1]>=k[0]?UP:DOWN;
        head.push('<span style="color:'+MUTED+'">开</span><span style="color:'+c+'">'+k[0]+'</span>');
        head.push('<span style="color:'+MUTED+'">收</span><span style="color:'+c+'">'+k[1]+'</span>');
        head.push('<span style="color:'+MUTED+'">低</span>'+k[2]);
        head.push('<span style="color:'+MUTED+'">高</span>'+k[3]);
    }
    var html=head.join(sep);
    var maParts=[];
    (meta.mas||[]).forEach(function(ma){
        var v=ma.data[di];
        if(v==null) return;
        maParts.push('<span style="color:'+ma.color+'">'+ma.name+'</span>'+Number(v).toFixed(2));
    });
    if(maParts.length) html+=sep+maParts.join(sep);
    var pct=meta.pct_change&&meta.pct_change[di];
    if(pct!=null){
        var pctClass=pct>=0?'color:'+UP:'color:'+DOWN;
        html+=sep+'<span style="'+pctClass+'">'+esc((pct>=0?'+':'')+Number(pct).toFixed(2)+'%')+'</span>';
    }
    var sigs=meta.signals[di]||[];
    sigs.forEach(function(s){
        var c=s.type==='BUY'?UP:DOWN;
        var line='<span style="color:'+c+';font-weight:700">'
            +(s.type==='BUY'?'买入':'卖出')+'·'+esc(s.strategy)+'</span> '
            +'<span style="color:'+MUTED+'">@</span>'+esc(s.price)+' ';
        if(s.freq) line+='<span style="color:'+MUTED+'">周期</span>'+esc(s.freq)+' ';
        if(s.strength!=null && s.strength!=='') line+='<span style="color:'+MUTED+'">强度</span>'+esc(s.strength)+' ';
        if(s.reason) line+='<span style="color:'+MUTED+'">'+esc(s.reason)+'</span>';
        html+='<div style="margin-top:2px">'+line+'</div>';
    });
    return html;
}
"""

_PAGE_CSS = """
:root{--bg:#0f1419;--panel:#161b22;--border:#2b333d;--text:#c9d1d9;--muted:#8b949e;
--up:#26a69a;--down:#ef5350;}
*{box-sizing:border-box;}
html,body{margin:0;background:var(--bg);color:var(--text);
font:14px/1.5 -apple-system,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif;}
header{padding:14px 20px;border-bottom:1px solid var(--border);display:flex;
align-items:center;gap:16px;flex-wrap:wrap;}
header h1{font-size:16px;margin:0;font-weight:600;}
.legend{display:flex;gap:18px;color:var(--muted);font-size:13px;}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;
vertical-align:middle;margin-right:5px;}
.charts{padding:8px 12px 24px;}
.chart{width:100%;margin-bottom:6px;background:var(--panel);
border:1px solid var(--border);border-radius:8px;}
.hint{color:var(--muted);font-size:12px;}
"""


def build_echarts_html(chart_configs: list[dict], metas: dict[str, dict]) -> str:
    """渲染多个 ECharts 实例的 HTML（Kline.html 外壳），charts 之间 connect 联动。"""
    divs: list[str] = []
    inits: list[str] = []
    opts: list[str] = []

    for cfg in chart_configs:
        cid = cfg["id"]
        h = cfg["height"]
        divs.append(f'<div id="{cid}" class="chart" style="height:{h}px;"></div>')
        inits.append(f'ch["{cid}"]=echarts.init(document.getElementById("{cid}"));')
        opt_json = json.dumps(cfg["option"], ensure_ascii=False)
        opt_json = opt_json.replace("</", "<\\/")
        opt_json = opt_json.replace(
            '"KLINE_TIP_POS"',
            "function(pt,params,dom,rect,size){return [220,6];}",
        )
        opt_json = opt_json.replace(
            '"KLINE_AXIS_TIP"',
            f'function(params){{return klineAxisTip(params,KLINE_META["{cid}"]);}}',
        )
        opt_json = opt_json.replace(
            '"KLINE_VOL_FORMATTER"',
            "function(v){if(v>=1e8)return (v/1e8).toFixed(2)+'亿';if(v>=1e4)return (v/1e4).toFixed(2)+'万';return v>=1?v.toFixed(2):v;}",
        )
        opt_json = opt_json.replace(
            '"KLINE_PRICE_FORMATTER"',
            "function(v){return v>=1?Number(v).toFixed(2):v;}",
        )
        opts.append(f'ch["{cid}"].setOption({opt_json});')

    meta_json = json.dumps(metas, ensure_ascii=False)
    meta_json = meta_json.replace("</", "<\\/")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
<style>{_PAGE_CSS}</style>
</head><body>
<header>
  <h1>K线多标的联动 · 买卖信号叠加</h1>
  <div class="legend">
    <span><span class="dot" style="background:var(--up)"></span>买入 BUY</span>
    <span><span class="dot" style="background:var(--down)"></span>卖出 SELL</span>
    <span class="hint">滚轮/拖拽缩放 · 十字光标与缩放多图同步 · 鼠标移到 K 线查看信号详情</span>
  </div>
</header>
<div id="charts" class="charts">{"".join(divs)}</div>
<script>
{_TIP_JS}
var KLINE_META={meta_json};
(function(){{var ch={{}};
{"".join(inits)}
var lst=Object.values(ch);
lst.forEach(function(c){{if(c)c.group='kline-group';}});
if(lst.length)echarts.connect('kline-group');
{"".join(opts)}
window.addEventListener("resize",function(){{lst.forEach(function(c){{if(c)c.resize();}});}});
}})();
</script></body></html>"""
    return html
