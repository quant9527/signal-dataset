"""BC XD4 signal filter group page (url_path=signal_bc_xd4).

页面提供一组预置的 signal 表筛选 SQL，分别展示匹配结果；
同时筛选出最近 5 天内出现过大涨的 symbol，再展示这些 symbol 的 bc_xd4 信号。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data import get_surge_symbols, get_weekly_dif_positive_symbols, query_signals_by_rule
from signal_constants import AS_ALL_EXCHANGES, BC_XD4_PREFIX
from utils import display_signals_multiview, get_cached_data


# AS 模式全局限制：exchange 必须落在 as_all 范围内
_AS_ALL_IN = "exchange IN ('as','ths','asindex')"


# -----------------------------------------------------------------------------
# 预置筛选 SQL：每个条目对应一个子视图
# -----------------------------------------------------------------------------
_FILTER_SQLS: list[dict[str, str | bool]] = [
    {
        "name": "bc_xd4 全部",
        "description": "AS 模式范围内 signal_name 以 bc_xd4 开头的全部信号",
        "where_clause": f"signal_name LIKE '{BC_XD4_PREFIX}%' AND {_AS_ALL_IN}",
    },
    {
        "name": "bc_xd4 A 股个股",
        "description": "A 股个股（as）且 signal_name 以 bc_xd4 开头",
        "where_clause": f"exchange = 'as' AND signal_name LIKE '{BC_XD4_PREFIX}%'",
    },
    {
        "name": "bc_xd4 大周期",
        "description": "AS 模式范围内 signal_name 以 bc_xd4 开头且 freq 为大周期 (1d/1w/1M)",
        "where_clause": (
            f"signal_name LIKE '{BC_XD4_PREFIX}%' "
            f"AND freq IN ('1d', '1w', '1M') AND {_AS_ALL_IN}"
        ),
    },
    {
        "name": "bc_xd4 周线",
        "description": "AS 模式范围内 signal_name 以 bc_xd4 开头且 freq 为 1w",
        "where_clause": f"signal_name LIKE '{BC_XD4_PREFIX}%' AND freq = '1w' AND {_AS_ALL_IN}",
    },
    {
        "name": "bc_xd4 做多方向",
        "description": "AS 模式范围内 signal_name 以 bc_xd4 开头且 side 为 long",
        "where_clause": (
            f"signal_name LIKE '{BC_XD4_PREFIX}%' AND side = 'long' AND {_AS_ALL_IN}"
        ),
    },
    {
        "name": "bc_xd4 1h + 周线 DIF>0",
        "description": "AS 模式范围内 1h 周期出现 bc_xd4，且对应 symbol 的周线 MACD DIF 在零轴上方",
        "where_clause": (
            f"signal_name LIKE '{BC_XD4_PREFIX}%' AND freq = '1h' AND {_AS_ALL_IN}"
        ),
        "requires_weekly_dif": True,
    },
]


def _load_bc_xd4_signals(days: int = 45) -> pd.DataFrame:
    """加载最近 N 天的 bc_xd4 系列信号，并限制在 AS 模式范围内。"""
    df = get_cached_data(days, signal_name_prefix=BC_XD4_PREFIX)
    if df.empty:
        return df
    if "signal_date" in df.columns:
        df["signal_date"] = pd.to_datetime(df["signal_date"])
    if "exchange" in df.columns:
        df = df[df["exchange"].isin(AS_ALL_EXCHANGES)].copy()
    return df


def _filter_by_date_range(df: pd.DataFrame, start_date, end_date) -> pd.DataFrame:
    """按信号日期范围过滤。"""
    if df.empty or "signal_date" not in df.columns:
        return df
    return df[
        (df["signal_date"].dt.date >= start_date)
        & (df["signal_date"].dt.date <= end_date)
    ].copy()


def _render_sql_filter_section(df_full: pd.DataFrame) -> None:
    """渲染「信号筛选 SQL」区域：每个 SQL 一个 expander + 结果表格。"""
    st.divider()
    st.subheader("1️⃣ 信号筛选 SQL 结果")
    st.caption("以下每组 SQL 独立查询 signal 表，展示匹配到的信号（受上方日期范围过滤）。")

    if df_full.empty:
        st.info("暂无 bc_xd4 信号数据，无法执行筛选 SQL。")
        return

    for idx, item in enumerate(_FILTER_SQLS, start=1):
        with st.expander(f"{idx}. {item['name']} — {item['description']}", expanded=False):
            st.code(item["where_clause"], language="sql")
            result_df = query_signals_by_rule(item["where_clause"], limit=500)
            if not result_df.empty and "signal_date" in result_df.columns:
                result_df["signal_date"] = pd.to_datetime(result_df["signal_date"])
                min_date = df_full["signal_date"].dt.date.min()
                max_date = df_full["signal_date"].dt.date.max()
                result_df = result_df[
                    (result_df["signal_date"].dt.date >= min_date)
                    & (result_df["signal_date"].dt.date <= max_date)
                ].copy()

            # 特殊信号集：1h bc_xd4 + 周线 DIF > 0
            if item.get("requires_weekly_dif") and not result_df.empty:
                required_cols = {"symbol", "exchange"}
                if required_cols.issubset(result_df.columns):
                    with st.spinner("拉取周线数据并计算 MACD DIF…"):
                        pairs = list(
                            zip(
                                result_df["symbol"].astype(str).str.strip(),
                                result_df["exchange"].astype(str).str.strip(),
                            )
                        )
                        positive_pairs = get_weekly_dif_positive_symbols(pairs)
                        positive_set = set(positive_pairs)
                        mask = result_df.apply(
                            lambda row: (
                                str(row["symbol"]).strip(),
                                str(row["exchange"]).strip(),
                            )
                            in positive_set,
                            axis=1,
                        )
                        result_df = result_df[mask].copy()
                else:
                    st.warning("结果缺少 symbol/exchange 列，无法执行周线 DIF 过滤。")
                    result_df = pd.DataFrame()

            if result_df.empty:
                st.info("该条件下无匹配信号。")
            else:
                # 用 symbol_id 替代 exchange / symbol / symbol_name 三列
                if {"exchange", "symbol"}.issubset(result_df.columns):
                    result_df["symbol_id"] = (
                        result_df["exchange"].astype(str).str.strip()
                        + "_"
                        + result_df["symbol"].astype(str).str.strip()
                    )
                    display_cols = [
                        "id",
                        "pick_id",
                        "symbol_id",
                        "freq",
                        "signal_date",
                        "signal_name",
                        "side",
                        "price",
                        "score",
                        "reason",
                        "created_at",
                    ]
                    keep_cols = [c for c in display_cols if c in result_df.columns]
                    result_df = result_df[keep_cols].copy()

                unique_symbols = (
                    result_df["symbol_id"].nunique()
                    if "symbol_id" in result_df.columns
                    else result_df["symbol"].nunique()
                )
                st.write(
                    f"匹配到 **{unique_symbols}** 个标的，"
                    f"共 **{len(result_df)}** 条信号。"
                )
                st.dataframe(
                    result_df,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "id": st.column_config.NumberColumn("ID", width="small"),
                        "pick_id": st.column_config.TextColumn("Pick ID", width="small"),
                        "symbol_id": st.column_config.TextColumn("symbol_id", width="medium"),
                        "signal_name": st.column_config.TextColumn("信号名", width="medium"),
                        "signal_date": st.column_config.DatetimeColumn("信号时间", width="medium"),
                        "freq": st.column_config.TextColumn("周期", width="small"),
                        "side": st.column_config.TextColumn("方向", width="small"),
                        "price": st.column_config.NumberColumn("价格", format="%.4f"),
                        "score": st.column_config.NumberColumn("评分", format="%.2f"),
                        "reason": st.column_config.TextColumn("原因", width="large"),
                        "created_at": st.column_config.DatetimeColumn("创建时间", width="medium"),
                    },
                )


def _render_surge_section(df_full: pd.DataFrame) -> None:
    """渲染「最近5天大涨 symbol 的 bc_xd4 信号」区域。"""
    st.divider()
    st.subheader("2️⃣ 最近5天出现过大涨的 symbol 的 bc_xd4 信号")
    st.caption(
        "仅 **exchange = as** 的标的；从 Flight (quant-lab) 拉取最近5天日线，"
        "计算日涨幅，筛选出任意一天涨幅 ≥ 7% 的 symbol，再展示其 bc_xd4 信号。"
    )

    if df_full.empty:
        st.info("暂无 bc_xd4 信号数据。")
        return

    if "exchange" not in df_full.columns:
        st.warning("信号数据中无 exchange 列，无法筛选 A 股标的。")
        return

    as_df = df_full[df_full["exchange"] == "as"].copy()
    if as_df.empty:
        st.info("当前无 A 股（as）bc_xd4 信号。")
        return

    symbols = as_df["symbol"].dropna().astype(str).str.strip().unique().tolist()
    if not symbols:
        st.info("无可用 A 股代码。")
        return

    threshold = st.number_input(
        "大涨阈值 (%)",
        min_value=1.0,
        max_value=20.0,
        value=7.0,
        step=0.5,
        key="bc_xd4_surge_threshold",
    )
    days = st.number_input(
        "回看天数",
        min_value=1,
        max_value=30,
        value=5,
        step=1,
        key="bc_xd4_surge_days",
    )

    if st.button("🔍 查询最近大涨 symbol", type="primary", key="bc_xd4_surge_btn"):
        with st.spinner("从 Flight 拉取行情并计算大涨标的…"):
            surge_symbols = get_surge_symbols(
                symbols,
                exchange="as",
                days=int(days),
                threshold=threshold / 100.0,
            )

        if not surge_symbols:
            st.info(
                f"最近 {int(days)} 天内，bc_xd4 信号涉及的 A 股标的中 "
                f"无涨幅 ≥ {threshold}% 的记录。"
            )
            return

        surge_df = as_df[as_df["symbol"].astype(str).str.strip().isin(surge_symbols)].copy()
        if surge_df.empty:
            st.info("大涨标的中无 bc_xd4 信号记录。")
            return

        st.success(
            f"最近 {int(days)} 天内共 **{len(surge_symbols)}** 个标的涨幅 ≥ {threshold}%，"
            f"其中涉及 **{surge_df['symbol'].nunique()}** 个标的的 bc_xd4 信号。"
        )
        display_signals_multiview(surge_df, height=600, show_stats=True)


def page_signal_bc_xd4() -> None:
    """BC XD4 信号页面入口。"""
    st.set_page_config(layout="wide", page_title="BC XD4 Signals")
    st.header("📊 BC XD4 信号筛选")
    st.markdown(f"""
**说明**：展示 `signal_name` 以 `{BC_XD4_PREFIX}` 开头的信号。

- **第 1 区**：按预置 SQL 条件分别展示信号结果。
- **第 2 区**：筛选最近 5 天内出现过大涨的 A 股 symbol，展示其 bc_xd4 信号。
""")
    st.divider()

    df_full = _load_bc_xd4_signals(days=45)

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
        st.info(f"📅 显示 {date_range[0]} 至 {date_range[1]} 的 bc_xd4 信号。")
    else:
        st.warning("暂无 bc_xd4 信号数据。")

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
                st.metric("🔝 最多信号周期", f"{top_freq} ({freq_counts.iloc[0]})" if len(freq_counts) > 0 else "N/A")

    _render_sql_filter_section(df_full)
    _render_surge_section(df_full)