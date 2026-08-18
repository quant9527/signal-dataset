"""Backtest reports page (url_path=backtest_reports).

从 PostgreSQL ``public.signal`` 表读取信号记录，按 run_id 分组展示，
join ``public.backtest_report`` 拿回测元信息。
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd
import psycopg
import streamlit as st


# ---------- 数据库连接 ----------

def _get_db_url() -> str | None:
    """优先读取 ``.streamlit/secrets.toml``，其次环境变量 ``DATABASE_URL``。"""
    try:
        return st.secrets["connections"]["quantdb"]["url"]
    except (KeyError, FileNotFoundError, Exception):
        pass
    return os.environ.get("DATABASE_URL")


def _get_connection():
    """建立到 quant 数据库的连接。"""
    url = _get_db_url()
    if not url:
        raise RuntimeError(
            "未配置数据库连接。请检查 .streamlit/secrets.toml 或 DATABASE_URL 环境变量。"
        )
    return psycopg.connect(url)


# ---------- 数据查询 ----------

def _summary_rows() -> list[dict[str, Any]]:
    """从 ``backtest_report`` 拉列表，n_signals/n_symbols/freqs 从 ``signal`` 聚合补充。"""
    query = """
    SELECT
        r.run_id,
        r.pick_id,
        r.source,
        r.start_date,
        r.end_date,
        r.freqs AS report_freqs,
        r.version,
        r.n_symbols AS report_n_symbols,
        r.n_signals AS report_n_signals,
        r.n_trades,
        r.total_return,
        r.annual_return,
        r.sharpe,
        r.max_dd,
        r.created_at,
        COALESCE(s.actual_n_signals, r.n_signals) AS n_signals,
        COALESCE(s.actual_n_symbols, r.n_symbols) AS n_symbols,
        s.earliest_signal_date,
        s.latest_signal_date,
        s.freqs
    FROM public.backtest_report r
    LEFT JOIN (
        SELECT
            run_id,
            COUNT(*) AS actual_n_signals,
            COUNT(DISTINCT symbol_id) AS actual_n_symbols,
            MIN(signal_date) AS earliest_signal_date,
            MAX(signal_date) AS latest_signal_date,
            STRING_AGG(DISTINCT freq, ',' ORDER BY freq) AS freqs
        FROM public.signal
        GROUP BY run_id
    ) s ON s.run_id = r.run_id
    ORDER BY r.created_at DESC
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            cols = [desc[0] for desc in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_signals_by_run_id(run_id: str) -> pd.DataFrame:
    """按 run_id 查询信号明细并展平为 DataFrame。"""
    query = """
    SELECT
        symbol_id,
        exchange,
        symbol,
        freq,
        symbol_name,
        signal_date,
        signal_name,
        signal,
        side,
        reason,
        price,
        score,
        shares,
        info,
        version,
        pick_id,
        run_id,
        pick_dt
    FROM public.signal
    WHERE run_id = %s
    ORDER BY signal_date DESC, symbol_id
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (run_id,))
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty and "signal_date" in df.columns:
        df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    if not df.empty and "pick_dt" in df.columns:
        df["pick_dt"] = pd.to_datetime(df["pick_dt"], errors="coerce")
    return df


def _get_report_meta(run_id: str) -> dict[str, Any] | None:
    """按 run_id 从 backtest_report 取元信息（无记录则返回 None）。"""
    query = """
    SELECT
        run_id, pick_id, source, start_date, end_date, freqs,
        version, n_symbols, n_signals, n_trades,
        total_return, annual_return, sharpe, max_dd, created_at
    FROM public.backtest_report
    WHERE run_id = %s
    LIMIT 1
    """
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            cols = [desc[0] for desc in cur.description]
            return dict(zip(cols, row))


def _get_top_bot_trades(run_id: str, n: int = 20) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按 run_id 取收益最高 / 最低的 n 笔 trade（return_pct NULL 视为未平仓，跳过）。

    每行额外生成 ``kline_url``，指向 signalview 的 K 线页
    （``/kline?symbol=<symbol_id>&start=<entry-7d>&end=<exit+7d>``），
    方便观察信号出现前后的 K 线走势。
    """
    base_sql = """
    SELECT
        symbol_id, freq, direction, entry_ts, exit_ts,
        entry_price, exit_price, size, pnl, return_pct
    FROM public.backtest_trade
    WHERE run_id = %s AND return_pct IS NOT NULL
    """
    top_sql = base_sql + " ORDER BY return_pct DESC LIMIT %s"
    bot_sql = base_sql + " ORDER BY return_pct ASC LIMIT %s"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(top_sql, (run_id, n))
            top_cols = [desc[0] for desc in cur.description]
            top_rows = cur.fetchall()
            cur.execute(bot_sql, (run_id, n))
            bot_rows = cur.fetchall()
    top_df = pd.DataFrame(top_rows, columns=top_cols)
    bot_df = pd.DataFrame(bot_rows, columns=top_cols)
    for df in (top_df, bot_df):
        if not df.empty:
            for col in ("entry_ts", "exit_ts"):
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors="coerce")
            df["kline_url"] = df.apply(_build_kline_url, axis=1)
    return top_df, bot_df


def _build_kline_url(row: pd.Series) -> str:
    """生成 signalview K 线页 URL（前后 ±7 天窗口，便于观察信号前后走势）。"""
    symbol_id = str(row.get("symbol_id") or "")
    entry = row.get("entry_ts")
    exit_ = row.get("exit_ts")
    # 默认窗口：entry-30d ~ exit+30d（fallback 用于缺时间戳的行）
    end_dt = exit_ if pd.notna(exit_) else (entry if pd.notna(entry) else pd.Timestamp.utcnow())
    start_dt = entry if pd.notna(entry) else (end_dt - pd.Timedelta(days=30))
    start = (start_dt - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    end = (end_dt + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    return f"/kline?symbol={symbol_id}&start={start}&end={end}"


# ---------- 列表页 ----------

def list_reports(force_rebuild: bool = False) -> pd.DataFrame:
    """返回所有信号分组列表 DataFrame。

    ``force_rebuild`` 参数仅保留兼容旧签名，已无实际作用（数据来源是数据库，
    无需再构建文件索引）。
    """
    rows = _summary_rows()
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    for col in ("earliest_signal_date", "latest_signal_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


# ---------- 详情页 ----------

def _render_detail(run_id: str) -> None:
    """从数据库加载并渲染单个 run_id 的信号详情，并展示 backtest_report 元信息。"""
    sigs = _get_signals_by_run_id(run_id)
    if sigs.empty:
        st.error(f"找不到信号：{run_id}")
        return

    report = _get_report_meta(run_id)
    title = f"📈 {run_id}"
    if report:
        title += f"  (pick_id={report.get('pick_id', '')})"
    st.subheader(title)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("信号数", len(sigs))
    c2.metric("标的数", sigs["symbol_id"].nunique())
    c3.metric("周期", ", ".join(sorted(sigs["freq"].dropna().unique())) or "-")
    if report and report.get("sharpe") is not None:
        c4.metric("Sharpe", f"{report['sharpe']:.2f}")
    elif report:
        c4.metric("回测来源", report.get("source", "-"))

    if report:
        st.divider()
        st.markdown("**回测报告（backtest_report）**")
        rc1, rc2, rc3, rc4, rc5 = st.columns(5)
        rc1.metric("总收益", f"{report['total_return']*100:.2f}%" if report.get("total_return") is not None else "-")
        rc2.metric("年化", f"{report['annual_return']*100:.2f}%" if report.get("annual_return") is not None else "-")
        rc3.metric("最大回撤", f"{report['max_dd']*100:.2f}%" if report.get("max_dd") is not None else "-")
        rc4.metric("交易笔数", report.get("n_trades", 0) or 0)
        rc5.metric("起止", f"{report.get('start_date', '-')}~{report.get('end_date', '-')}")
    else:
        st.warning(
            f"run_id={run_id} 在 backtest_report 表里没有记录，仅展示 signal 明细。"
        )

    st.divider()
    st.markdown(f"**信号明细（{len(sigs)} 条）**")
    st.dataframe(sigs, width="stretch", height=400)

    # top/bot 20 交易（按 return_pct 排序）
    top_df, bot_df = _get_top_bot_trades(run_id, n=20)
    st.divider()
    st.subheader("💰 交易表现 Top 20 / Bottom 20")
    if top_df.empty and bot_df.empty:
        st.info("该 run 暂无 trade 明细（backtest_trade 表为空，可能是老 run 或未产生交易）。")
    else:
        col_top, col_bot = st.columns(2)
        with col_top:
            st.markdown("**🟢 收益最高 20 笔**")
            if top_df.empty:
                st.caption("（无）")
            else:
                display_top = top_df.copy()
                if "return_pct" in display_top.columns:
                    display_top["return_pct"] = display_top["return_pct"].apply(
                        lambda v: f"{v:.2%}" if pd.notna(v) else "-"
                    )
                if "pnl" in display_top.columns:
                    display_top["pnl"] = display_top["pnl"].apply(
                        lambda v: f"{v:,.0f}" if pd.notna(v) else "-"
                    )
                for c in ("entry_ts", "exit_ts"):
                    if c in display_top.columns:
                        display_top[c] = pd.to_datetime(display_top[c]).dt.strftime(
                            "%Y-%m-%d %H:%M"
                        )
                display_top.rename(
                    columns={
                        "symbol_id": "symbol_id",
                        "freq": "周期",
                        "direction": "方向",
                        "entry_ts": "入场",
                        "exit_ts": "出场",
                        "entry_price": "入场价",
                        "exit_price": "出场价",
                        "size": "仓位",
                        "pnl": "盈亏",
                        "return_pct": "收益率",
                        "kline_url": "K线",
                    },
                    inplace=True,
                )
                _render_trades_table(display_top, height=420)
        with col_bot:
            st.markdown("**🔴 亏损最大 20 笔**")
            if bot_df.empty:
                st.caption("（无）")
            else:
                display_bot = bot_df.copy()
                if "return_pct" in display_bot.columns:
                    display_bot["return_pct"] = display_bot["return_pct"].apply(
                        lambda v: f"{v:.2%}" if pd.notna(v) else "-"
                    )
                if "pnl" in display_bot.columns:
                    display_bot["pnl"] = display_bot["pnl"].apply(
                        lambda v: f"{v:,.0f}" if pd.notna(v) else "-"
                    )
                for c in ("entry_ts", "exit_ts"):
                    if c in display_bot.columns:
                        display_bot[c] = pd.to_datetime(display_bot[c]).dt.strftime(
                            "%Y-%m-%d %H:%M"
                        )
                display_bot.rename(
                    columns={
                        "symbol_id": "symbol_id",
                        "freq": "周期",
                        "direction": "方向",
                        "entry_ts": "入场",
                        "exit_ts": "出场",
                        "entry_price": "入场价",
                        "exit_price": "出场价",
                        "size": "仓位",
                        "pnl": "盈亏",
                        "return_pct": "收益率",
                        "kline_url": "K线",
                    },
                    inplace=True,
                )
                _render_trades_table(display_bot, height=420)


def _render_trades_table(df: pd.DataFrame, height: int) -> None:
    """渲染 top/bot trade 表：K线 列渲染为可点击链接。"""
    column_config = {
        "K线": st.column_config.LinkColumn(
            label="K线",
            help="跳转 signalview K 线页（窗口 = 入场前 7d ~ 出场后 7d）",
            display_text="🔗 K线",
        ),
        "收益率": st.column_config.TextColumn("收益率"),
        "盈亏": st.column_config.TextColumn("盈亏"),
    }
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        height=height,
        column_config=column_config,
    )


# ---------- 删除 ----------

def delete_report(run_id: str) -> list[str]:
    """删除指定 run_id 的所有信号记录。"""
    query = "DELETE FROM public.signal WHERE run_id = %s"
    with _get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (run_id,))
            deleted = cur.rowcount
        conn.commit()
    return [run_id] if deleted else []


# ---------- 页面入口 ----------

def page_backtest_reports() -> None:
    st.set_page_config(page_title="Backtest Reports", layout="wide")
    st.title("📊 回测报告管理")
    st.caption(
        "主表：``backtest_report``（按 run_id 一行一次回测，含 sharpe / 总收益 / "
        "最大回撤等指标）；明细：``signal`` 表按 run_id 关联展示。"
    )

    if st.button("🔄 刷新列表", width="content"):
        st.rerun()

    df = list_reports()
    if df.empty:
        st.info(
            "暂无回测报告。运行以下命令生成：\n\n"
            "```bash\n"
            "# 离线回测（写 backtest_report + signal）\n"
            "python -m vbt.run_and_save cl2b_pair --target as --freq 1d \\\n"
            "    --start 2026-01-01 --end 2026-07-01\n"
            "\n"
            "# 或测试用例\n"
            "pytest -v vbt/cl2b_triangle_test.py -k test_backtest_as -m slow\n"
            "```"
        )
        st.stop()

    filter_text = st.text_input(
        "筛选记录", placeholder="run_id / pick_id / 周期 / 日期"
    ).strip().lower()
    if filter_text:
        mask = df.astype(str).apply(
            lambda row: row.str.lower().str.contains(filter_text, na=False).any(),
            axis=1,
        )
        df = df[mask]

    if df.empty:
        st.info("没有匹配筛选条件的记录。")
        st.stop()

    st.subheader(f"共 {len(df)} 个 run")

    _display_df = df[
        [
            "run_id",
            "pick_id",
            "latest_signal_date",
            "n_signals",
            "n_symbols",
            "freqs",
            "sharpe",
            "total_return",
            "max_dd",
        ]
    ].copy()
    for col in ("latest_signal_date",):
        ts = pd.to_datetime(_display_df[col], errors="coerce")
        _display_df[col] = ts.dt.strftime("%Y-%m-%d %H:%M:%S").fillna("-")
    for col, fmt in (("total_return", "{:.2%}"), ("max_dd", "{:.2%}"), ("sharpe", "{:.2f}")):
        _display_df[col] = _display_df[col].apply(
            lambda v: fmt.format(v) if pd.notna(v) else "-"
        )
    _display_df["详情"] = _display_df["run_id"].apply(
        lambda rid: f"/backtest_report_detail?run_id={rid}"
    )
    _display_df["删除"] = False
    _display_df.rename(
        columns={
            "run_id": "run_id",
            "pick_id": "策略",
            "latest_signal_date": "最新信号时间",
            "n_signals": "信号数",
            "n_symbols": "标的数",
            "freqs": "周期",
            "sharpe": "Sharpe",
            "total_return": "总收益",
            "max_dd": "最大回撤",
        },
        inplace=True,
    )
    _display_df = _display_df[
        ["删除", "run_id", "策略", "最新信号时间", "信号数", "标的数", "周期",
         "Sharpe", "总收益", "最大回撤", "详情"]
    ]

    edited = st.data_editor(
        _display_df,
        width="stretch",
        hide_index=True,
        column_config={
            "删除": st.column_config.CheckboxColumn(
                label="删除",
                help="勾选要删除的 run（点击下方按钮执行）",
                default=False,
            ),
            "详情": st.column_config.LinkColumn(
                label="详情",
                help="跳转到该 run 的信号/交易明细页",
                display_text="📑 详情",
            ),
            "run_id": st.column_config.TextColumn("run_id", disabled=True),
            "策略": st.column_config.TextColumn("策略", disabled=True),
            "最新信号时间": st.column_config.TextColumn("最新信号时间", disabled=True),
            "信号数": st.column_config.NumberColumn("信号数", disabled=True),
            "标的数": st.column_config.NumberColumn("标的数", disabled=True),
            "周期": st.column_config.TextColumn("周期", disabled=True),
            "Sharpe": st.column_config.TextColumn("Sharpe", disabled=True),
            "总收益": st.column_config.TextColumn("总收益", disabled=True),
            "最大回撤": st.column_config.TextColumn("最大回撤", disabled=True),
        },
        key="runs_table",
    )

    to_delete = edited.loc[edited["删除"] == True, "run_id"].tolist()  # noqa: E712
    if to_delete and st.button(
        f"🗑️ 删除选中的 {len(to_delete)} 个 run", type="primary"
    ):
        deleted_all = []
        for run_id in to_delete:
            deleted_all.extend(delete_report(run_id))
        st.success(f"已删除 {len(deleted_all)} 个 run：{', '.join(deleted_all)}")
        st.rerun()
