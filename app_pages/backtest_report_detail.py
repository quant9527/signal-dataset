"""Backtest report detail page (url_path=backtest_report_detail).

接收 ?run_id=<run_id> 查询参数，从 ``public.signal`` 表渲染该 run 下的
所有信号明细，并展示 ``backtest_report`` 元信息（sharpe / 总收益等）。
"""
from __future__ import annotations

import streamlit as st

import app_pages.backtest_reports as br


def page_backtest_report_detail() -> None:
    st.set_page_config(page_title="Backtest Report Detail", layout="wide")

    run_id = st.query_params.get("run_id", "")
    if not run_id:
        st.warning("缺少查询参数 ?run_id=<run_id>。")
        st.stop()

    br._render_detail(run_id)
