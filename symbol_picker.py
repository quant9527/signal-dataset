"""
可复用的多交易所 Symbol 选择器组件。

提供四个函数：
- symbol_picker_add_ui — 交易所 + 可搜索代码下拉 + 添加按钮
- symbol_quick_add_ui — 渲染常用标的 pills，点击直接添加（如 asindex:sh000300）
- symbol_picker_selected_ui — 已选标的（exchange:symbol）展示 + 点击取消删除
- symbol_tokens_selected_ui — 已选编码 token（如 as:000001:1d）展示 + 点击取消删除

用途：用于 K 线页、信号搜索页等需要用户选择不同交易所标的的场景。
"""

from __future__ import annotations

from typing import Any, Callable, NamedTuple

import pandas as pd
import streamlit as st

from constants import (
    EXCHANGE_AS_ALL,
    KLINE_DEFAULT_FREQ,
    KLINE_EXCHANGE_OPTIONS,
    KLINE_EXCHANGE_SELECT_OPTIONS,
    KLINE_FREQ_SET,
)
from data import get_instruments_by_exchange
from signal_constants import AS_ALL_EXCHANGES


def _split_symbol_input(raw: str) -> list[str]:
    """将逗号/中文逗号分隔的代码串解析为列表。"""
    return [s.strip() for s in raw.replace("，", ",").split(",") if s.strip()]


def parse_symbols_with_exchange(
    raw: str, default_exchange: str
) -> list[tuple[str, str]]:
    """解析逗号分隔的 symbol 列表，支持 exchange:symbol 格式。"""
    result: list[tuple[str, str]] = []
    for s in _split_symbol_input(raw):
        if ":" in s:
            ex, sym = s.split(":", 1)
            ex = ex.strip().lower()
            sym = sym.strip()
        else:
            ex = default_exchange.lower()
            sym = s.strip()
        if not sym:
            continue
        if ex not in KLINE_EXCHANGE_OPTIONS:
            ex = default_exchange
        result.append((ex, sym))
    return result


def _clean_symbol_code(sym: str) -> str:
    """去掉 instrument 表中 symbol 列的后缀元数据，只保留纯代码。

    某些 instrument 表的 symbol 列存储格式为 "代码_名称_拼音别名"（如
    "881145_电力_dl_DL"），而 Flight 查询只需要纯代码。
    """
    if "_" in sym:
        prefix = sym.split("_", 1)[0]
        if prefix.isdigit() and len(prefix) == 6:
            return prefix
    return sym


def _instruments_for_exchange(exchange: str) -> pd.DataFrame:
    """按交易所获取 instrument；as_all 时合并 as/ths/asindex 三张表。

    返回列与 get_instruments_by_exchange 一致：exchange, symbol, name, sub_exchange, alias。
    """
    if exchange == EXCHANGE_AS_ALL:
        frames = [
            f for ex in AS_ALL_EXCHANGES if not (f := get_instruments_by_exchange(ex)).empty
        ]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)
    return get_instruments_by_exchange(exchange)


def symbol_picker_add_ui(key_prefix: str = "sp") -> tuple[str, str] | None:
    """
    Render exchange selector + searchable symbol dropdown + add button in one row.

    下拉选项包含「代码  名称  [别名]」，alias 中包含拼音首字母，
    Streamlit 自带搜索可直接匹配（如输入"jfy"找到"减肥药"）。

    Returns
    -------
    (exchange, symbol) | None
        点「＋ 添加」时返回 (exchange, symbol)，否则返回 None。
    """
    c1, c2, c3 = st.columns([1, 2, 1], vertical_alignment="bottom")
    with c1:
        exchange_options = list(KLINE_EXCHANGE_SELECT_OPTIONS)
        a_exchange: str = st.selectbox(
            "交易所",
            options=exchange_options,
            index=exchange_options.index(EXCHANGE_AS_ALL),
            key=f"{key_prefix}_exchange",
            label_visibility="collapsed",
            placeholder="交易所",
        )

    is_as_all = a_exchange == EXCHANGE_AS_ALL
    add_inst = _instruments_for_exchange(a_exchange)
    with c2:
        if not add_inst.empty:
            if is_as_all:
                # 合集下代码会跨交易所重复，用 "exchange:symbol" 作为选项值以消歧
                sym_list = sorted(
                    add_inst["exchange"].astype(str) + ":" + add_inst["symbol"].astype(str)
                )
                display_prefix = True
            else:
                sym_list = sorted(add_inst["symbol"].tolist())
                display_prefix = False

            name_map: dict[str, Any] = {}
            alias_map: dict[str, str] = {}
            for _, row in add_inst.iterrows():
                key = (
                    f"{row['exchange']}:{row['symbol']}"
                    if display_prefix
                    else str(row["symbol"])
                )
                name_map[key] = row["name"]
                if "alias" in add_inst.columns:
                    aliases = row.get("alias")
                    if isinstance(aliases, (list, tuple)):
                        sym_low = str(row["symbol"]).lower()
                        nam_low = str(row.get("name", "")).lower()
                        extra = [
                            str(a)
                            for a in aliases
                            if str(a).lower() not in (sym_low, nam_low)
                        ]
                        if extra:
                            alias_map[key] = "_".join(extra)

            def _fmt(s: str) -> str:
                ex_part = ""
                sym_part = s
                if display_prefix:
                    ex_part, sym_part = s.split(":", 1)
                label = f"{sym_part}"
                if display_prefix:
                    label = f"{ex_part}:{sym_part}"
                name = name_map.get(s, "")
                alias = alias_map.get(s, "")
                if name:
                    label = f"{label}_{name}"
                if alias:
                    label = f"{label}_{alias}"
                return label

            a_symbol: str = st.selectbox(
                "代码",
                options=sym_list,
                format_func=_fmt,
                key=f"{key_prefix}_symbol_select",
                label_visibility="collapsed",
                placeholder="代码",
            )
        else:
            a_symbol = st.text_input(
                "代码",
                key=f"{key_prefix}_symbol_input",
                placeholder="600519 / sh000300 / BTC",
                label_visibility="collapsed",
            )

    with c3:
        add_clicked = st.button("添加", key=f"{key_prefix}_add", width="stretch")

    if add_clicked:
        raw_val = str(a_symbol).strip()
        if not raw_val:
            return None
        if is_as_all:
            if ":" in raw_val:
                ex, sym = raw_val.split(":", 1)
                ex = ex.strip().lower()
                if ex in AS_ALL_EXCHANGES:
                    sym_val = _clean_symbol_code(sym.strip())
                    if sym_val:
                        return (ex, sym_val)
            return None
        sym_val = _clean_symbol_code(raw_val)
        if sym_val:
            return (a_exchange, sym_val)
    return None


def symbol_quick_add_ui(
    presets: list[tuple[str, str]],
    label_func: Callable[[str, str], str] | None = None,
    selected: set[tuple[str, str]] | None = None,
    key_prefix: str = "sp_quick",
) -> tuple[str, str] | None:
    """
    快捷添加标的：渲染一排可切换的按钮，点击后返回该标的。

    按钮会根据当前是否已选切换样式：已选为 primary，未选为 tertiary。

    Parameters
    ----------
    presets : list[tuple[str, str]]
        预设的 (exchange, symbol) 列表，如 [("asindex", "sh000300"), ...]。
    label_func : Callable[[str, str], str] | None
        自定义按钮显示文本，接收 (exchange, symbol) 返回 label；
        为空时默认显示 "exchange:symbol"。
    selected : set[tuple[str, str]] | None
        当前已选中的预设标的集合，用于决定按钮样式。
    key_prefix : str
        Streamlit widget key 前缀。

    Returns
    -------
    tuple[str, str] | None
        用户点击某个按钮时返回对应的 (exchange, symbol)；否则返回 None。
    """
    if not presets:
        return None

    _label = label_func or (lambda ex, sym: f"{ex}:{sym}")
    selected_set = selected or set()

    with st.container(horizontal=True):
        for i, (ex, sym) in enumerate(presets):
            is_selected = (ex, sym) in selected_set
            display = _label(ex, sym)
            if st.button(
                display,
                key=f"{key_prefix}_btn_{i}",
                type="primary" if is_selected else "tertiary",
                help=f"{'取消选择' if is_selected else '选择'} {ex}:{sym}",
            ):
                return (ex, sym)
    return None


def symbol_picker_selected_ui(
    selected: list[tuple[str, str]],
    key_prefix: str = "sp",
) -> int | None:
    """
    已选标的：使用按钮展示，点击即可删除。

    Parameters
    ----------
    selected : list[tuple[str, str]]
        当前已选的 (exchange, symbol) 列表。
    key_prefix : str
        Streamlit widget key 前缀。

    Returns
    -------
    int | None
        用户删除了哪个 index 的项，否则 None。
    """
    st.markdown(f"**已选标的（{len(selected)}）**")
    options = [f"{ex}:{sym}" for ex, sym in selected]
    if not options:
        return None

    clicked_idx: int | None = None
    with st.container(horizontal=True):
        for i, label in enumerate(options):
            if st.button(f"{label} ×", key=f"{key_prefix}_del_{i}", type="tertiary"):
                clicked_idx = i
    return clicked_idx


# ============================================================
# K 线 URL symbol 编码：exchange:symbol[:freq][:reverse]，逗号分隔多个
# freq 段缺失/为空时，SymbolToken.freq = None；具体语义由消费页面定义。
# ============================================================


class SymbolToken(NamedTuple):
    """K 线单个标的的完整参数（对应 URL 中一段 token）。

    `freq` 为 None 表示 URL token 中 freq 段缺失/为空，具体含义（如隐藏）
    由消费页面定义；本模块保持协议层语义中立。
    """

    exchange: str
    symbol: str
    freq: str | None = KLINE_DEFAULT_FREQ
    reverse: bool = False

    @property
    def token(self) -> str:
        return encode_symbol_token(self.exchange, self.symbol, self.freq, self.reverse)


def encode_symbol_token(
    exchange: str,
    symbol: str,
    freq: str | None = KLINE_DEFAULT_FREQ,
    reverse: bool = False,
) -> str:
    """编码为 URL token：`as:000001:1d`、`as:000001` 或 `asindex:sh000300:1w:reverse`。"""
    ex = str(exchange).strip().lower()
    sym = str(symbol).strip()
    if freq is None:
        base = f"{ex}:{sym}"
    else:
        fq = freq if freq in KLINE_FREQ_SET else KLINE_DEFAULT_FREQ
        base = f"{ex}:{sym}:{fq}"
    return f"{base}:reverse" if reverse else base


def parse_symbol_tokens(raw: str | None) -> list[SymbolToken]:
    """解析 URL `symbol` 参数（逗号分隔的 token 列表）。"""
    if not raw:
        return []
    entries: list[SymbolToken] = []
    for tok in _split_symbol_input(raw):
        parts = tok.split(":")
        if len(parts) < 2:
            continue
        ex = parts[0].strip().lower()
        sym = parts[1].strip()
        reverse = len(parts) >= 3 and parts[-1].strip().lower() == "reverse"
        if reverse:
            parts = parts[:-1]
        freq = parts[2].strip() if len(parts) > 2 else None
        if not ex or not sym:
            continue
        if freq and freq not in KLINE_FREQ_SET:
            freq = KLINE_DEFAULT_FREQ
        entries.append(SymbolToken(ex, sym, freq or None, reverse))
    return entries


def symbol_tokens_selected_ui(
    tokens: list[str],
    key_prefix: str = "spt",
    show_clear_button: bool = False,
) -> int | str | None:
    """
    已选 token 展示（如 `as:000001:1d`、`asindex:sh000300:1w:reverse`），
    以可点击的 pills 按钮形式展示，点击即可删除。

    Parameters
    ----------
    tokens : list[str]
        当前已选 token 列表。
    key_prefix : str
        Streamlit widget key 前缀。
    show_clear_button : bool
        是否在标题右侧显示「清空」按钮。

    Returns
    -------
    int | str | None
        用户删除了哪个 index 的项；点「清空」时返回 "clear"；否则返回 None。
    """
    c1, c2 = st.columns([4, 1], vertical_alignment="center")
    with c1:
        st.markdown(f"**已选标的（{len(tokens)}）**")
    with c2:
        clear_clicked = (
            show_clear_button
            and tokens
            and st.button("清空", key=f"{key_prefix}_clear", type="tertiary")
        )

    options = list(tokens)
    state_key = f"{key_prefix}_selected_tags"
    options_key = f"{key_prefix}_options"
    if not options:
        # 清理旧状态，避免下次新增 token 时被旧选项干扰
        if state_key in st.session_state:
            del st.session_state[state_key]
        if options_key in st.session_state:
            del st.session_state[options_key]
        return "clear" if clear_clicked else None

    # 当 options 列表发生变化（URL 新增/删除 token）时，重置选中态为当前全部
    prev_options = st.session_state.get(options_key)
    if prev_options != options:
        st.session_state[state_key] = options
        st.session_state[options_key] = options

    # 避免同时传 default 和通过 session_state 设值而触发 Streamlit 警告
    kwargs: dict[str, Any] = {"label_visibility": "collapsed"}
    if state_key not in st.session_state:
        kwargs["default"] = options

    curr_selected = st.pills(
        "已选标的",
        options=options,
        selection_mode="multi",
        key=state_key,
        **kwargs,
    )
    curr_selected = curr_selected if isinstance(curr_selected, list) else []
    removed = [x for x in options if x not in curr_selected]
    if removed:
        return options.index(removed[0])
    if clear_clicked:
        return "clear"

    return None
