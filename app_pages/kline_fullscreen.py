"""
K 线图表页：Kline.html 风格渲染（深色面板、固定 tooltip、箭头 BUY/SELL 信号、联动）。

- 单页合并：顶部为参数设置 UI（标的选 + 周期/日期/信号），底部为 ECharts K 线图。
- 业务状态全部保存在 URL query params；widget 自身 state 仅用于 plumbing。
- `symbol=exchange:symbol[:freq][:reverse]`，逗号分隔多个；无 freq 表示该 symbol 隐藏（保留控制栏，不拉取/不渲染）。
- `start` / `end` 全局日期；按 (freq, reverse) 分组分别调用 Flight，再按 symbol 提取。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as st_html

import data
import flight_kline_client as fkc
from app_pages import _kline_common as common
from app_pages import kline_charts as kc
from constants import KLINE_DEFAULT_FREQ, kline_freq_options_for_exchange
from symbol_picker import (
    SymbolToken,
    encode_symbol_token,
    parse_symbol_tokens,
    symbol_picker_add_ui,
    symbol_quick_add_ui,
)

SYMBOL_CHART_HEIGHT = 600  # 单标的兜底高度

# 快捷添加的常用标的
KLINE_QUICK_ADD_PRESETS: list[tuple[str, str]] = [
    ("asindex", "sh000300"),
    ("asindex", "sh000001"),
    ("asindex", "sz399006"),
    ("asindex", "sh000688"),
    ("asindex", "sh000852"),
    ("ths", "883957"),
]


def _symbol_chart_height(chart_count: int) -> int:
    """根据图表数量动态计算单个图表高度。"""
    if chart_count <= 1:
        return SYMBOL_CHART_HEIGHT
    if chart_count == 2:
        return 420
    if chart_count == 3:
        return 320
    return 280


def _sync_url_params(
    entries: list[SymbolToken],
    start_d: date,
    end_d: date,
    all_signals: bool,
) -> None:
    """首次加载时把缺失的默认参数回写到 URL，使 URL 始终完整。"""
    expected_symbol = ",".join(e.token for e in entries) if entries else ""
    expected_start = start_d.isoformat()
    expected_end = end_d.isoformat()
    expected_all = "1" if all_signals else "0"

    cur_symbol = common.qp_str("symbol")
    cur_start = common.qp_str("start")
    cur_end = common.qp_str("end")
    cur_all = common.qp_str("all_signals")

    if not entries:
        if "symbol" in st.query_params:
            del st.query_params["symbol"]
        return

    changed = False
    if cur_symbol != expected_symbol:
        st.query_params["symbol"] = expected_symbol
        changed = True
    if cur_start != expected_start:
        st.query_params["start"] = expected_start
        changed = True
    if cur_end != expected_end:
        st.query_params["end"] = expected_end
        changed = True
    if cur_all != expected_all and expected_all != "1":
        # 只在关闭 all_signals 时写 "0"；默认 "1" 可省略
        st.query_params["all_signals"] = expected_all
        changed = True
    if changed:
        st.rerun()


def _widget_key_safe(value: str) -> str:
    """把字符串中的非字母数字字符替换为下划线，生成 Streamlit widget key。"""
    return "".join(c if c.isalnum() else "_" for c in value)


@st.cache_data(ttl=600, show_spinner=False)
def _build_preset_name_map(
    presets: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], str]:
    """从 instrument 表查询快捷添加预设的中文名称。"""
    result: dict[tuple[str, str], str] = {}
    exchanges = {ex for ex, _ in presets}
    for ex in exchanges:
        df = data.get_instruments_by_exchange(ex)
        if df.empty:
            continue
        df = df.copy()
        df["_sym_lower"] = df["symbol"].astype(str).str.lower()
        for ex_p, sym_p in presets:
            if ex_p.lower() != ex.lower():
                continue
            match = df[df["_sym_lower"] == sym_p.lower()]
            if not match.empty:
                result[(ex_p, sym_p)] = str(match.iloc[0].get("name", ""))
    return {preset: result.get(preset) or f"{preset[0]}:{preset[1]}" for preset in presets}


def _preset_label(exchange: str, symbol: str) -> str:
    names = _build_preset_name_map(tuple(KLINE_QUICK_ADD_PRESETS))
    return names.get((exchange, symbol), f"{exchange}:{symbol}")


@st.cache_data(ttl=600, show_spinner=False)
def _build_symbol_name_map(
    exchanges_symbols: tuple[tuple[str, str], ...],
) -> dict[tuple[str, str], str]:
    """按 exchange 查询 instrument 表，构建 (exchange, symbol) -> name 映射。"""
    result: dict[tuple[str, str], str] = {}
    exchanges = {ex for ex, _ in exchanges_symbols}
    for ex in exchanges:
        df = data.get_instruments_by_exchange(ex)
        if df.empty:
            continue
        for _, row in df.iterrows():
            sym = str(row.get("symbol", "")).strip()
            name = str(row.get("name", "")).strip()
            if sym and name:
                result[(ex, sym)] = name
    return result


def _symbol_label_func(
    name_map: dict[tuple[str, str], str],
) -> Callable[[SymbolToken], str]:
    """快捷 label 函数：优先中文名，其次 exchange:symbol。"""
    def label(e: SymbolToken) -> str:
        return name_map.get((e.exchange, e.symbol)) or f"{e.exchange}:{e.symbol}"
    return label


def _chart_title(token: SymbolToken, name_map: dict[tuple[str, str], str]) -> str:
    """图表标题：优先显示 symbol 名称，保留 token 作为副信息。"""
    name = name_map.get((token.exchange, token.symbol))
    if name:
        return f"{name} · {token.token}"
    return token.token


def _group_entries(entries: list[SymbolToken]) -> dict[tuple[str, bool], list[SymbolToken]]:
    groups: dict[tuple[str, bool], list[SymbolToken]] = {}
    for e in entries:
        if e.freq is None:
            continue
        groups.setdefault((e.freq, e.reverse), []).append(e)
    return groups


# Frequency fallback chain: requested freq → 1d → no data.
# Triggered when Flight returns empty for the requested freq (e.g. server side
# 1w data not ingested). Keeps the page from going blank-red when someone
# shares a URL with a freq the server doesn't carry.
_FREQ_FALLBACK = ("1d",)


def _default_new_entry_freq(entries: list[SymbolToken]) -> str:
    """新增标的继承首个可见标的的周期；首个为 hidden 或无标的时使用默认周期。"""
    if entries and entries[0].freq:
        return entries[0].freq
    return KLINE_DEFAULT_FREQ


def _fetch_groups(
    groups: dict[tuple[str, bool], list[SymbolToken]],
    start_ms: int,
    end_ms: int,
    flight_url: str,
) -> dict[tuple[str, bool], pd.DataFrame]:
    """按 (freq, reverse) 分组拉取 Flight K 线。

    派生周期（`1w` / `1M`）服务端不直接入库，按 quant-lab `lab/data.py:296-297`
    的做法：tag 用 `1d` 作为基础频，让 Flight 服务端按 `kline_aggregate="1w"`
    在原始 1d 数据上聚合后返回。
    """
    frames: dict[tuple[str, bool], pd.DataFrame] = {}
    for (freq, reverse), group in groups.items():
        is_derived = freq in ("1w", "1M")
        # 派生周期用 1d 作 tag 后缀；非派生周期 tag 直接用 freq。
        base_freq = "1d" if is_derived else freq
        tags: list[str] = []
        for e in group:
            tags.extend(fkc.build_kline_tags([e.symbol], e.exchange, base_freq))
        if not tags:
            continue
        raw = fkc.fetch_kline_dataframe(
            tags,
            start_ms,
            end_ms,
            flight_url=flight_url or None,
            kline_reverse=reverse,
            kline_aggregate=freq if is_derived else "",
        )
        if raw is not None and not raw.empty:
            frames[(freq, reverse)] = raw
    return frames


def _entry_sym_key(e: SymbolToken) -> str | None:
    tags = fkc.build_kline_tags([e.symbol], e.exchange, e.freq)
    return kc.symbol_key_from_tags(tags)


def _build_charts(
    entries: list[SymbolToken],
    frames: dict[tuple[str, bool], pd.DataFrame],
    start_d: date,
    end_d: date,
    all_signals: bool = False,
) -> tuple[list[dict], dict[str, dict], dict[str, int]]:
    """构建对比图 + 各标的图；返回 (chart_configs, metas, bar_counts)。"""
    visible_entries = [e for e in entries if e.freq is not None]
    sym_data: dict[str, tuple[pd.DataFrame, dict]] = {}
    for e in visible_entries:
        frame = frames.get((e.freq, e.reverse))
        sk = _entry_sym_key(e)
        if frame is None or sk is None:
            continue
        parsed = kc.extract_symbol_data(frame, sk, exchange=e.exchange)
        if parsed is not None:
            sym_data[e.token] = parsed

    if not sym_data:
        return [], {}, {}

    name_map = _build_symbol_name_map(tuple((e.exchange, e.symbol) for e in visible_entries))

    charts: list[dict] = []
    metas: dict[str, dict] = {}
    chart_height = _symbol_chart_height(len(visible_entries))

    for e in visible_entries:
        if e.token not in sym_data:
            continue
        prep, meta = sym_data[e.token]
        labels = kc.date_labels(prep["_x"], freq=e.freq)
        ohlc = kc.to_echarts_ohlc(prep)
        vol = kc.to_echarts_volume(prep)
        ma_lines = kc.to_echarts_ma(prep, meta["ma_cols"])
        boll_lines = kc.to_echarts_boll(prep)
        macd = kc.to_echarts_macd(prep, meta["macd"])
        has_vol = meta["has_volume"] and prep["volume"].notna().any()

        signal_freq = None if all_signals else e.freq
        signals_df = data.get_kline_signals(e.exchange, e.symbol, start_d, end_d, freq=signal_freq)
        signals = kc.map_signals_to_bars(prep, signals_df, chart_freq=signal_freq)

        cid = f"ch_{len(metas)}"
        pct_change_raw = prep.get("pct_change")
        pct_change_list: list[float | None] | None = None
        if pct_change_raw is not None and not pct_change_raw.isna().all():
            pct_change_list = [
                None if pd.isna(v) else round(float(v), 2)
                for v in pct_change_raw
            ]
        charts.append({
            "id": cid,
            "height": chart_height,
            "option": kc.build_symbol_candle_option(
                title=_chart_title(e, name_map),
                labels=labels,
                ohlc=ohlc,
                volume=vol,
                ma_lines=ma_lines,
                macd=macd,
                has_volume=has_vol,
                signals=signals or None,
                height=chart_height,
                boll_lines=boll_lines,
            ),
        })
        metas[cid] = kc.build_chart_meta(labels, ohlc, ma_lines, signals, pct_change_list, boll_lines=boll_lines)

    bar_counts = {tok: len(prep) for tok, (prep, _) in sym_data.items()}
    return charts, metas, bar_counts


def _redirect_when_empty(raw_symbol: str) -> None:
    """当 URL 中缺少有效 symbol 参数时，展示空状态引导用户添加。

    单 Page 设计下不再 switch_page 到 kline.py，原地提示即可。
    """
    st.info("请通过「添加标的」选择至少一个标的，或通过 URL 参数 `symbol` 传入标的。")
    st.stop()


# K 线页业务状态全部挂在 URL query params 上；清空即回到默认状态。
_KLINE_QUERY_KEYS = ("symbol", "start", "end", "all_signals")


def _clear_to_default() -> None:
    """清空 K 线页全部状态（标的、日期、信号开关），回到默认空状态。"""
    for key in _KLINE_QUERY_KEYS:
        if key in st.query_params:
            del st.query_params[key]
    # 同时重置页内所有 widget 的 session_state，避免旧值在 rerun 后残留。
    for key in list(st.session_state.keys()):
        if key.startswith("kfs_"):
            del st.session_state[key]
    st.rerun()


def page_kline_fullscreen() -> None:
    st.set_page_config(layout="wide", page_title="K 线")
    st.markdown(
        "<style>div.block-container{padding-top:4.5rem;padding-bottom:0.5rem;}</style>",
        unsafe_allow_html=True,
    )

    default_end = date.today()
    default_start = default_end - timedelta(days=365)

    raw_symbol = common.qp_str("symbol")
    entries = parse_symbol_tokens(raw_symbol)

    start_d = common.parse_iso_date(common.qp_str("start")) or default_start
    end_d = common.parse_iso_date(common.qp_str("end")) or default_end
    # 默认显示全部周期信号
    all_signals = True if "all_signals" not in st.query_params else common.qp_bool("all_signals")
    if start_d > end_d:
        st.error("开始日期不能晚于结束日期。")
        st.stop()

    # 首次加载时将默认参数写回 URL
    _sync_url_params(entries, start_d, end_d, all_signals)

    name_map = _build_symbol_name_map(tuple((e.exchange, e.symbol) for e in entries))
    _name_of = _symbol_label_func(name_map)

    # ---------- 快捷添加 ----------
    preset_set = set(KLINE_QUICK_ADD_PRESETS)
    selected_presets = {
        (e.exchange, e.symbol) for e in entries
        if (e.exchange, e.symbol) in preset_set
    }
    non_preset_tokens = [
        e.token for e in entries
        if (e.exchange, e.symbol) not in preset_set
    ]

    clicked_preset = symbol_quick_add_ui(
        KLINE_QUICK_ADD_PRESETS,
        label_func=_preset_label,
        selected=selected_presets,
        key_prefix="kfs_quick",
    )
    if clicked_preset is not None:
        new_presets = selected_presets ^ {clicked_preset}
        default_freq = _default_new_entry_freq(entries)
        preset_tokens = [
            encode_symbol_token(ex_p, sym_p, default_freq)
            for ex_p, sym_p in new_presets
        ]
        st.query_params["symbol"] = ",".join([*non_preset_tokens, *preset_tokens])
        st.rerun()

    # ---------- 搜索添加 ----------
    add_result = symbol_picker_add_ui(key_prefix="kfs_add")
    if add_result is not None:
        ex, sym = add_result
        default_freq = _default_new_entry_freq(entries)
        new_token = encode_symbol_token(ex, sym, default_freq)
        if new_token not in {e.token for e in entries}:
            st.query_params["symbol"] = ",".join(
                e.token for e in [*entries, SymbolToken(ex, sym, default_freq)]
            )
            st.rerun()

    if not entries:
        _redirect_when_empty(raw_symbol)

    # ---------- 标的控制栏（freq pills + popover 删除）----------
    freq_changed = False
    new_entries: list[SymbolToken] = []
    removed_idx: int | None = None
    for i, e in enumerate(entries):
        label = _name_of(e)
        with st.container(border=True):
            c_chip, c_freq = st.columns([3, 8], vertical_alignment="center", gap="small")
            with c_chip:
                with st.popover(
                    label,
                    icon=":material/settings:",
                    help=f"{label} · 点开管理该标的",
                ):
                    if st.button(
                        "删除该标的",
                        key=f"kfs_rm_{i}",
                        type="secondary",
                        icon=":material/delete:",
                        width="stretch",
                    ):
                        removed_idx = i
            with c_freq:
                # 同一只标的可能以不同频率同时出现（如 as:002827:1h 与 as:002827:1d），
                # key 必须包含列表索引才能唯一。
                pills_key = f"kfs_freq_pills_{i}_{e.exchange}_{_widget_key_safe(e.symbol)}"
                freq_options = kline_freq_options_for_exchange(e.exchange)
                new_freq = st.pills(
                    f"周期_{i}",
                    options=list(freq_options),
                    default=e.freq if e.freq in freq_options else None,
                    key=pills_key,
                    label_visibility="collapsed",
                )
                if new_freq != e.freq:
                    freq_changed = True
                    new_entries.append(SymbolToken(e.exchange, e.symbol, new_freq, e.reverse))
                else:
                    new_entries.append(e)

    entries = new_entries
    if removed_idx is not None:
        remaining = [e for i, e in enumerate(entries) if i != removed_idx]
        if remaining:
            st.query_params["symbol"] = ",".join(e.token for e in remaining)
        elif "symbol" in st.query_params:
            del st.query_params["symbol"]
        st.rerun()
    if freq_changed:
        st.query_params["symbol"] = ",".join(e.token for e in entries)
        st.rerun()

    # ---------- 空可见集兜底 ----------
    if not any(e.freq is not None for e in entries):
        st.info("所有标的均已隐藏，请为其选择周期。")
        st.stop()

    # ---------- 日期 & 信号设置 ----------
    c_d1, c_d2, c_sig, c_clear = st.columns([2, 2, 3, 1], vertical_alignment="center", gap="small")
    with c_d1:
        start_input = st.date_input("开始日期", value=start_d, key="kfs_start")
    with c_d2:
        end_input = st.date_input("结束日期", value=end_d, key="kfs_end")
    with c_sig:
        all_signals_input = st.checkbox(
            "显示全部周期信号",
            value=all_signals,
            key="kfs_all_signals",
            help="开启后叠加所有周期（15m/30m/1h/1d/1w）的买卖信号",
        )
    with c_clear:
        if st.button(
            "清空",
            key="kfs_clear",
            icon=":material/restart_alt:",
            type="secondary",
            width="stretch",
            help="清除标的、日期与信号设置，回到默认状态",
        ):
            _clear_to_default()

    if start_input > end_input:
        st.error("开始日期不能晚于结束日期。")
        st.stop()

    date_or_signal_changed = (
        start_input != start_d
        or end_input != end_d
        or all_signals_input != all_signals
    )
    if date_or_signal_changed:
        st.query_params["start"] = start_input.isoformat()
        st.query_params["end"] = end_input.isoformat()
        st.query_params["all_signals"] = "1" if all_signals_input else "0"
        st.rerun()

    # ---------- 数据拉取 ----------
    st.divider()
    start_ms = int(pd.Timestamp(start_d, tz="Asia/Shanghai").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end_d, tz="Asia/Shanghai").replace(hour=23, minute=59, second=59).timestamp() * 1000)
    flight_url = kc.resolve_flight_url()

    # 记录每个 entry 实际请求的 freq（fallback 时用于回写 URL / 提示用户）。
    requested_freq: dict[str, str] = {
        e.token: e.freq for e in entries if e.freq is not None
    }

    groups = _group_entries(entries)
    with st.spinner("正在从 Flight 拉取 K 线…"):
        frames = _fetch_groups(groups, start_ms, end_ms, flight_url)

    # 找不到数据的 entry：按 entry 粒度 fallback 到 _FREQ_FALLBACK 中的 freq，
    # 避免整个页面因个别 freq 服务端缺数据而红框。
    fallback_used: list[tuple[str, str, str]] = []  # (token, requested, actual)
    for fb_freq in _FREQ_FALLBACK:
        # 找出当前还需要拉、且目标 freq 不是 fb_freq 的 entry
        fb_groups: dict[tuple[str, bool], list[SymbolToken]] = {}
        for e in entries:
            if e.freq is None:
                continue
            if (e.freq, e.reverse) in frames:
                continue  # 已经拉到了
            if e.freq == fb_freq:
                continue  # 已经按这个 freq 试过，跳过
            fb_groups.setdefault((fb_freq, e.reverse), []).append(
                SymbolToken(e.exchange, e.symbol, fb_freq, e.reverse)
            )
        if not fb_groups:
            continue
        fb_frames = _fetch_groups(fb_groups, start_ms, end_ms, flight_url)
        # 把 fallback 拉到结果挂到 (fb_freq, reverse) 这个 key。
        # 再把这些 entry 的 freq 改写为 fb_freq，让 _build_charts 能取到 frame。
        for i, e in enumerate(entries):
            if e.freq is None:
                continue
            if (e.freq, e.reverse) in frames:
                continue
            if (fb_freq, e.reverse) in fb_frames and not fb_frames[(fb_freq, e.reverse)].empty:
                entries[i] = SymbolToken(e.exchange, e.symbol, fb_freq, e.reverse)
                frames[(fb_freq, e.reverse)] = fb_frames[(fb_freq, e.reverse)]
                fallback_used.append((e.token, requested_freq[e.token], fb_freq))

    if not frames:
        st.error("拉取失败或该时间范围内无数据：请确认 Flight 服务已启动，且已安装 `pyarrow`。")
        st.stop()

    if fallback_used:
        st.info(
            "以下标的在请求的周期下 Flight 无数据，已自动降级到 `1d`："
            + "、".join(
                f"{tok}({req}→{act})" for tok, req, act in fallback_used
            )
        )
        # 把 freq 同步到 URL，使后续刷新直接用 1d 不再触发 fallback 链。
        # 不调 st.rerun() — fallback 已生效，图表可以直接渲染。
        st.query_params["symbol"] = ",".join(
            e.token for e in entries if e.freq is not None
        )

    charts, metas, bar_counts = _build_charts(entries, frames, start_d, end_d, all_signals=all_signals)
    if not charts:
        st.warning("未找到与请求匹配的标的行。")
        st.stop()

    full_html = kc.build_echarts_html(charts, metas)
    total_h = sum(c["height"] for c in charts) + len(charts) * 8 + 90
    st_html(full_html, height=total_h)

    total_bars = sum(bar_counts.values())
    st.caption(f"共 {len(bar_counts)} 个标的 · 总计 {total_bars} 根 K 线")
