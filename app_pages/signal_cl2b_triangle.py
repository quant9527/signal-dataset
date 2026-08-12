"""CL2B triangle signal page (url_path=signal_cl2b_triangle).

页面展示 AS 模式范围内 `signal_name` 以 `cl2b_triangle` 开头的信号，
并按「同花顺板块（ths）」与「A 股个股（as）」两个维度分别展示。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from signal_constants import CL2B_TRIANGLE_PREFIX
from utils import display_signals_multiview, get_cached_data


# 本页只展示 THS 板块与 A 股个股两类标的
_PAGE_EXCHANGES: tuple[str, ...] = ("as", "ths")


def _load_cl2b_triangle_signals(days: int = 45) -> pd.DataFrame:
    """加载最近 N 天的 cl2b_triangle 系列信号，并限制在 as/ths 范围内。"""
    df = get_cached_data(days, signal_name_prefix=CL2B_TRIANGLE_PREFIX)
    if df.empty:
        return df
    df = df.copy()
    if "signal_date" in df.columns:
        df["signal_date"] = pd.to_datetime(df["signal_date"])
    if "exchange" in df.columns:
        df = df[df["exchange"].isin(_PAGE_EXCHANGES)].copy()
    return df


def _filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """按信号日期范围过滤。"""
    if df.empty or "signal_date" not in df.columns:
        return df
    return df[
        (df["signal_date"].dt.date >= start_date)
        & (df["signal_date"].dt.date <= end_date)
    ].copy()


def _render_section(df: pd.DataFrame, title: str, exchange: str, height: int = 500) -> None:
    """渲染单个 exchange 分区的信号多视图。"""
    section_df = (
        df[df["exchange"] == exchange].copy()
        if "exchange" in df.columns and exchange
        else df.copy()
    )

    st.subheader(title)
    if section_df.empty:
        st.info(f"暂无 {exchange.upper() if exchange else ''} 的 cl2b_triangle 信号。")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.metric("📊 标的数量", section_df["symbol"].nunique())
    with col2:
        st.metric("📈 信号总数", len(section_df))

    display_signals_multiview(section_df, height=height, show_stats=False)


def page_signal_cl2b_triangle() -> None:
    """CL2B triangle 信号页面入口。"""
    st.set_page_config(layout="wide", page_title="CL2B Triangle Signals")
    st.header("📐 CL2B Triangle 信号")
    st.markdown(f"""
**说明**：展示 `signal_name` 以 `{CL2B_TRIANGLE_PREFIX}` 开头的信号。

- **THS 板块**：`exchange = ths` 的板块信号。
- **A 股个股**：`exchange = as` 的个股信号。
""")
    st.divider()

    df_full = _load_cl2b_triangle_signals(days=45)

    # 日期范围选择
    if not df_full.empty and "signal_date" in df_full.columns:
        min_date = df_full["signal_date"].dt.date.min()
        max_date = df_full["signal_date"].dt.date.max()
        unique_dates = sorted(df_full["signal_date"].dt.date.unique(), reverse=True)
        default_start = unique_dates[min(4, len(unique_dates) - 1)] if unique_dates else min_date

        date_range = st.slider(
            "选择信号日期范围",
            min_value=min_date,
            max_value=max_date,
            value=(default_start, max_date),
            format="YYYY-MM-DD",
        )
        df_full = _filter_by_date_range(df_full, date_range[0], date_range[1])
        st.info(f"📅 显示 {date_range[0]} 至 {date_range[1]} 的 cl2b_triangle 信号。")
    else:
        st.warning("暂无 cl2b_triangle 信号数据。")

    # 概览指标
    if not df_full.empty:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📊 标的数量", df_full["symbol"].nunique())
        with col2:
            st.metric("📈 信号总数", len(df_full))
        with col3:
            if "freq" in df_full.columns:
                freq_counts = df_full["freq"].value_counts()
                top_freq = freq_counts.index[0] if len(freq_counts) > 0 else "N/A"
                st.metric(
                    "🔝 最多信号周期",
                    f"{top_freq} ({freq_counts.iloc[0]})" if len(freq_counts) > 0 else "N/A",
                )

    # 按 THS 板块 / A 股个股分开展示
    if not df_full.empty:
        st.divider()
        tab_ths, tab_as = st.tabs(["🏢 THS 板块", "📈 A 股个股"])

        with tab_ths:
            _render_section(df_full, "THS 板块信号", "ths", height=500)

        with tab_as:
            _render_section(df_full, "A 股个股信号", "as", height=500)
