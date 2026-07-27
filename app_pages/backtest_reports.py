"""Backtest reports page (url_path=backtest_reports)."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime

import pandas as pd
import streamlit as st

# quant-lab 报告目录，可根据部署环境调整
QUANT_LAB_FILES = "/home/lei/repo/quant-lab/files"

# Streamlit static serving 路径（需配合 server.enableStaticServing=true）
STATIC_REPORTS_URL = "/app/static/reports"


def _extract_title(html_text: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE)
    return html.unescape(m.group(1).strip()) if m else "未命名报告"


def _extract_meta(html_text: str) -> str:
    m = re.search(r'<div class="meta">(.*?)</div>', html_text, re.IGNORECASE | re.DOTALL)
    return html.unescape(m.group(1).strip()) if m else ""


def _extract_summary(html_text: str) -> str:
    m = re.search(
        r'<h3[^>]*>执行摘要</h3>\s*<div class=[\'"]summary-box[\'"]>(.*?)</div>',
        html_text,
        re.DOTALL,
    )
    if m:
        text = re.sub(r"<[^>]+?>", "", m.group(1))
        return html.unescape(text.strip())[:200]
    return ""


def _parse_filename_dt(filename: str) -> datetime | None:
    m = re.search(r"(\d{8})_(\d{6})", filename)
    if m:
        dt_str = f"{m.group(1)} {m.group(2)}"
        return datetime.strptime(dt_str, "%Y%m%d %H%M%S")
    return None


def _base_name(filename: str) -> str:
    return os.path.splitext(filename)[0]


def list_reports() -> pd.DataFrame:
    """扫描 quant-lab/files/ 目录，返回报告列表 DataFrame。"""
    if not os.path.isdir(QUANT_LAB_FILES):
        return pd.DataFrame()

    rows = []
    for fname in sorted(os.listdir(QUANT_LAB_FILES), reverse=True):
        if not fname.endswith(".html") or fname == "index.html":
            continue
        path = os.path.join(QUANT_LAB_FILES, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                html_text = f.read()
        except Exception:
            continue

        base = _base_name(fname)
        pkl_path = os.path.join(QUANT_LAB_FILES, f"{base}.pkl")
        pkl_exists = os.path.exists(pkl_path)
        created_dt = _parse_filename_dt(fname)

        rows.append(
            {
                "filename": fname,
                "base": base,
                "title": _extract_title(html_text),
                "summary": _extract_summary(html_text),
                "meta": _extract_meta(html_text),
                "created_at": created_dt,
                "pkl_exists": pkl_exists,
                "html_path": path,
                "pkl_path": pkl_path if pkl_exists else None,
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty and "created_at" in df.columns:
        df = df.sort_values("created_at", ascending=False)
    return df


def delete_report(base: str) -> list[str]:
    """删除指定 base 的 html 和 pkl 文件，返回实际删除的文件名列表。"""
    deleted = []
    for ext in (".html", ".pkl"):
        path = os.path.join(QUANT_LAB_FILES, f"{base}{ext}")
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted.append(os.path.basename(path))
            except OSError:
                pass
    return deleted


def page_backtest_reports() -> None:
    st.set_page_config(page_title="Backtest Reports", layout="wide")
    st.title("📊 回测报告管理")
    st.caption(f"自动发现自 `{QUANT_LAB_FILES}`")

    if not os.path.isdir(QUANT_LAB_FILES):
        st.error(f"报告目录不存在：{QUANT_LAB_FILES}")
        st.stop()

    # 重新加载按钮
    if st.button("🔄 刷新列表", use_container_width=False):
        st.rerun()

    df = list_reports()

    if df.empty:
        st.info("暂无报告。在 quant-lab 中运行回测后会自动出现在这里。")
        st.stop()

    # 筛选
    filter_text = st.text_input("筛选报告", placeholder="策略名 / 日期 / 标的 / 周期").strip().lower()
    if filter_text:
        mask = df.astype(str).apply(lambda row: row.str.lower().str.contains(filter_text, na=False).any(), axis=1)
        df = df[mask]

    if df.empty:
        st.info("没有匹配筛选条件的报告。")
        st.stop()

    # 展示表格（点击“预览”在新窗口打开报告）
    st.subheader(f"共 {len(df)} 份报告")

    _display_df = df[["filename", "title", "summary", "meta", "created_at", "pkl_exists"]].copy()
    _display_df["created_at"] = _display_df["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    _display_df["pkl_exists"] = _display_df["pkl_exists"].map({True: "✅", False: "❌"})
    _display_df["预览"] = [
        f'<a href="{STATIC_REPORTS_URL}/{html.escape(fname)}" target="_blank">🔍 预览</a>'
        for fname in df["filename"]
    ]
    _display_df.rename(
        columns={
            "filename": "文件名",
            "title": "策略",
            "summary": "摘要",
            "meta": "回测信息",
            "created_at": "生成时间",
            "pkl_exists": "pkl",
        },
        inplace=True,
    )

    _html_table = _display_df.to_html(escape=False, index=False, classes="report-table")
    st.markdown(_html_table, unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        .report-table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .report-table th, .report-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
        .report-table th { background-color: #f5f5f5; font-weight: 600; }
        .report-table tr:hover { background-color: #fafafa; }
        .report-table a { text-decoration: none; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 删除区
    st.divider()
    st.subheader("🗑️ 删除报告")
    selected = st.multiselect(
        "选择要删除的报告",
        options=df["filename"].tolist(),
        format_func=lambda x: f"{x}  ({df[df['filename'] == x]['title'].iloc[0]})",
    )

    if selected:
        if st.button(f"🗑️ 删除选中的 {len(selected)} 份报告", type="primary"):
            deleted_all = []
            for fname in selected:
                base = _base_name(fname)
                deleted = delete_report(base)
                deleted_all.extend(deleted)
            st.success(f"已删除 {len(deleted_all)} 个文件：{', '.join(deleted_all)}")
            st.rerun()
