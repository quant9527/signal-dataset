"""Walk-Forward 对照页(walkfwd_compare.py)。

让用户在两个 PG run_id 之间对比:
- 元信息对比表(sharpe / total_return / max_dd / n_trades / win_rate)
- 净值曲线(equity)叠放对比
- 信号明细共享部分 vs 各自独有部分

入口:Streamlit page 路由注册 ``walkfwd_compare``;
使用方式:用户在 URL 末尾追加 ``?run_id_a=...&run_id_b=...``。
"""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

import app_pages.backtest_reports as br


def _normalize_metrics(metrics: dict[str, Any], run_id: str) -> dict[str, Any]:
    """把 backtest_report.stats_daily JSONB 字段归一化成扁平 dict。"""
    flat = {
        "run_id": run_id,
        "total_return": metrics.get("Total Return [%]"),
        "annual_return": metrics.get("Annualized Return [%]"),
        "sharpe": metrics.get("Sharpe Ratio"),
        "max_dd": metrics.get("Max Drawdown [%]"),
    }
    return flat


def page_walkfwd_compare() -> None:
    st.set_page_config(page_title="Walk-Forward Compare", layout="wide")
    st.title("🆚 Walk-Forward 对照(baseline vs ml_pick)")
    st.caption(
        "选择两个 run_id,signalview 会拉它们的元信息 + 信号明细做对照。"
        "典型用法:``cl2b_pair_baseline`` 与 ``cl2b_pair_mlpick`` 同一天的报告。"
    )

    run_id_a = st.query_params.get("run_id_a", "")
    run_id_b = st.query_params.get("run_id_b", "")

    if not run_id_a or not run_id_b:
        st.warning(
            "缺少查询参数:请用 ``?run_id_a=...&run_id_b=...`` 访问该页。"
        )
        # 给一个手动输入的回退
        with st.form("manual_run_id"):
            col1, col2 = st.columns(2)
            with col1:
                run_id_a = st.text_input(
                    "run_id A (baseline)", value=run_id_a,
                    placeholder="20260816_000938_cl2b_pair_baseline_v2",
                )
            with col2:
                run_id_b = st.text_input(
                    "run_id B (ml_pick)", value=run_id_b,
                    placeholder="20260816_001057_cl2b_pair_mlpick_v2",
                )
            submitted = st.form_submit_button("对照")
            if not submitted:
                st.stop()
            from urllib.parse import urlencode
            st.query_params.update({
                "run_id_a": run_id_a, "run_id_b": run_id_b,
            })
            st.rerun()

    # 拉元信息
    meta_a = br._get_report_meta(run_id_a)
    meta_b = br._get_report_meta(run_id_b)
    if meta_a is None or meta_b is None:
        st.error(
            f"未找到对应报告: a={run_id_a!r} ({'OK' if meta_a else 'MISS'}) "
            f"b={run_id_b!r} ({'OK' if meta_b else 'MISS'})"
        )
        st.stop()

    flat_a = _normalize_metrics(meta_a.get("stats_daily") or {}, run_id_a)
    flat_b = _normalize_metrics(meta_b.get("stats_daily") or {}, run_id_b)
    flat_a.update({
        "n_signals": meta_a.get("n_signals"),
        "n_trades": meta_a.get("n_trades"),
        "pick_id": meta_a.get("pick_id"),
    })
    flat_b.update({
        "n_signals": meta_b.get("n_signals"),
        "n_trades": meta_b.get("n_trades"),
        "pick_id": meta_b.get("pick_id"),
    })

    # 对照表
    rows = []
    for k in ["total_return", "annual_return", "sharpe", "max_dd",
              "n_signals", "n_trades"]:
        rows.append({
            "指标": k,
            "A (baseline)": flat_a.get(k),
            "B (ml_pick)": flat_b.get(k),
            "B - A": (
                (flat_b.get(k) - flat_a.get(k))
                if isinstance(flat_a.get(k), (int, float))
                and isinstance(flat_b.get(k), (int, float)) else None
            ),
        })
    st.subheader("📊 元信息对照")
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    # 信号明细交叉
    sig_a = br._get_signals_by_run_id(run_id_a)
    sig_b = br._get_signals_by_run_id(run_id_b)
    sig_a_keys = (
        set(zip(sig_a["symbol_id"], sig_a["signal_date"].astype(str)))
        if not sig_a.empty else set()
    )
    sig_b_keys = (
        set(zip(sig_b["symbol_id"], sig_b["signal_date"].astype(str)))
        if not sig_b.empty else set()
    )
    common = sig_a_keys & sig_b_keys
    only_a = sig_a_keys - sig_b_keys
    only_b = sig_b_keys - sig_a_keys

    st.subheader("📈 信号明细重叠")
    col1, col2, col3 = st.columns(3)
    col1.metric("A ∩ B (共同)", len(common))
    col2.metric("A - B (仅 baseline)", len(only_a))
    col3.metric("B - A (仅 ml_pick)", len(only_b))

    # 顶部 + 底部 trade 对照
    st.subheader("🏆 最佳 / 最差 top-10 交易")
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Run A")
        top_a, bot_a = br._get_top_bot_trades(run_id_a, n=10)
        if not top_a.empty:
            st.write("Top 10:")
            st.dataframe(top_a[["Column", "Entry Timestamp", "Exit Timestamp",
                                "Return"]].head(10), hide_index=True)
    with col2:
        st.caption("Run B")
        top_b, bot_b = br._get_top_bot_trades(run_id_b, n=10)
        if not top_b.empty:
            st.write("Top 10:")
            st.dataframe(top_b[["Column", "Entry Timestamp", "Exit Timestamp",
                                "Return"]].head(10), hide_index=True)
