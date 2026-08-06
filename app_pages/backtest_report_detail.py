"""Backtest report detail page (url_path=backtest_report_detail).

接收 ?base=<YYYYMMDD_HHMMSS_pick_id> 查询参数，渲染单次回测报告的完整内容。
入口来自 backtest_reports 列表中每行的"详情"按钮。
"""
from __future__ import annotations

import os

import streamlit as st

# 注意：必须用 ``import as`` 而不是 ``from ... import ...`` 取得模块名，
# 否则 ``br.QUANT_LAB_FILES`` 在测试或动态改写场景下会绑定到 import 时的
# 旧值，导致后续重定向失效（Python ``from X import Y`` 是名字绑定，
# 不是引用）。见 tests/test_backtest_reports.py 对该问题的回归。
import app_pages.backtest_reports as br


def page_backtest_report_detail() -> None:
    st.set_page_config(page_title="Backtest Report Detail", layout="wide")

    base = st.query_params.get("base", "")
    if not base:
        st.warning("缺少查询参数 ?base=<report_base>。")
        st.stop()

    pkl_path = os.path.join(br.QUANT_LAB_FILES, f"{base}.pkl")
    if not os.path.exists(pkl_path) or br._safe_load_pickle(pkl_path) is None:
        st.error(f"无法加载 pkl：{pkl_path}")
        st.stop()

    br._render_detail(base)