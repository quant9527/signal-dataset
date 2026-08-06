"""信号告警规则管理 — 增删改查页 (url_path=alert_rule_crud)."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data import (
    get_alert_rules,
    create_alert_rule,
    update_alert_rule,
    delete_alert_rule,
    toggle_alert_rule,
    query_signals_by_rule,
)
from utils import checkbox_data_editor


def page_alert_rule_crud() -> None:
    st.set_page_config(layout="wide", page_title="Alert Rules")
    st.header("🔔 信号告警规则管理")
    st.caption("管理 alert_rule 表：配置 signal 表的查询条件，匹配时发送飞书通知")
    st.divider()

    # ============================================================================
    # 上方两列：规则管理(左宽) | 新建规则(右窄)
    # ============================================================================
    rules_df = get_alert_rules()

    col_left, col_right = st.columns([2, 1])

    with col_right:
        st.subheader("📝 新建规则")
        with st.form("create_rule_form", clear_on_submit=True):
            new_name = st.text_input("规则名称 *", placeholder="如 bollinger_long",
                                     help="唯一标识，用于区分规则")
            new_title = st.text_input("告警标题", placeholder="如 布林带突破-做多",
                                      help="飞书消息标题，留空则用规则名称")
            new_desc = st.text_area("详细描述", value="", height=80,
                                    placeholder="描述监控目的、触发条件和预期行为",
                                    help="规则的详细说明")
            new_where = st.text_area(
                "WHERE 条件 *",
                value="""pick_id = 1
    AND signal_name = 'bollinger_breakout'
    AND exchange = 'as'
    AND side = 'long'""",
                height=140,
                help="查询 signal 表的 WHERE 条件（不含 WHERE 关键字）。常用字段: exchange, pick_id, signal_name, side, freq, symbol",
            )
            new_group = st.text_input("飞书群组", value="quant-alert",
                                      help="飞书群组名称（需已在 feishu client 中配置）")
            new_enabled = st.checkbox("启用", value=True)
            submitted = st.form_submit_button("创建规则", width="stretch", type="primary")
            if submitted:
                if not new_name.strip() or not new_where.strip():
                    st.warning("规则名称和 WHERE 条件不能为空")
                elif create_alert_rule(
                    name=new_name.strip(),
                    title=new_title.strip(),
                    description=new_desc.strip(),
                    where_clause=new_where.strip(),
                    feishu_group=new_group.strip() or "quant-alert",
                    enabled=new_enabled,
                ):
                    st.success(f"规则 `{new_name.strip()}` 创建成功")
                    st.rerun()
                else:
                    st.error("创建失败，请检查输入")

    with col_left:
        st.subheader("📋 规则列表")

        if rules_df.empty:
            st.info("暂无告警规则，请在右侧新建。")
        else:
            # 选择要操作的规则
            selected_rule_id = st.selectbox(
                "选择规则",
                options=rules_df["id"].tolist(),
                format_func=lambda rid: (
                    f"{rules_df[rules_df['id'] == rid]['name'].iloc[0]}"
                    f"({'🟢' if rules_df[rules_df['id'] == rid]['enabled'].iloc[0] else '🔴'})"
                ),
                key="rule_selector",
            )
            selected_rule = rules_df[rules_df["id"] == selected_rule_id].iloc[0]

            tab_signals, tab_edit, tab_detail = st.tabs(["📡 匹配信号", "✏️ 编辑规则", "ℹ️ 规则详情"])

            with tab_signals:
                st.caption(f"按规则 `{selected_rule['name']}` 的 WHERE 条件查询 signal 表")
                col_n, col_btn = st.columns([3, 1])
                with col_n:
                    sig_limit = st.number_input("查询条数", min_value=5, max_value=500,
                                                value=50, step=10, key="sig_limit")
                with col_btn:
                    st.markdown("###### &nbsp;")
                    run_query = st.button("🔍 查询", type="primary", width="stretch")

                if run_query:
                    with st.spinner("查询中..."):
                        signals_df = query_signals_by_rule(
                            selected_rule["where_clause"], limit=int(sig_limit)
                        )
                    if signals_df.empty:
                        st.info("暂无匹配信号")
                    else:
                        st.success(f"找到 {len(signals_df)} 条匹配信号")
                        st.dataframe(
                            signals_df,
                            hide_index=True,
                            width="stretch",
                            column_config={
                                "id": st.column_config.NumberColumn("ID", width="small"),
                                "pick_id": st.column_config.NumberColumn("Pick ID", width="small"),
                                "exchange": st.column_config.TextColumn("交易所", width="small"),
                                "symbol": st.column_config.TextColumn("代码", width="small"),
                                "freq": st.column_config.TextColumn("周期", width="small"),
                                "symbol_name": st.column_config.TextColumn("名称", width="medium"),
                                "signal_date": st.column_config.DatetimeColumn("信号时间", width="medium"),
                                "signal_name": st.column_config.TextColumn("信号名", width="medium"),
                                "side": st.column_config.TextColumn("方向", width="small"),
                                "price": st.column_config.NumberColumn("价格", format="%.4f"),
                                "score": st.column_config.NumberColumn("评分", format="%.2f"),
                                "reason": st.column_config.TextColumn("原因", width="large"),
                            },
                        )

            with tab_edit:
                with st.form("edit_rule_form"):
                    edit_name = st.text_input("规则名称",
                                              value=selected_rule["name"])
                    edit_title = st.text_input("告警标题",
                                               value=selected_rule["title"])
                    edit_desc = st.text_area("详细描述",
                                             value=selected_rule.get("description", ""),
                                             height=80)
                    edit_where = st.text_area(
                        "WHERE 条件",
                        value=selected_rule["where_clause"],
                        height=100,
                    )
                    edit_group = st.text_input("飞书群组",
                                               value=selected_rule["feishu_group"])
                    edit_enabled = st.checkbox("启用",
                                               value=selected_rule["enabled"])

                    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
                    with col_btn1:
                        saved = st.form_submit_button("💾 保存", type="primary",
                                                      width="stretch")
                    with col_btn2:
                        toggled = st.form_submit_button(
                            "🔄 禁用" if selected_rule["enabled"] else "🔄 启用",
                            width="stretch",
                        )
                    with col_btn3:
                        deleted = st.form_submit_button("🗑️ 删除", type="secondary",
                                                        width="stretch")

                    if saved:
                        if not edit_name.strip() or not edit_where.strip():
                            st.warning("规则名称和 WHERE 条件不能为空")
                        elif update_alert_rule(
                            selected_rule_id,
                            name=edit_name.strip() or None,
                            title=edit_title.strip() or None,
                            description=edit_desc.strip() or None,
                            where_clause=edit_where.strip() or None,
                            feishu_group=edit_group.strip() or None,
                            enabled=edit_enabled,
                        ):
                            st.success("更新成功")
                            st.rerun()

                    if toggled:
                        if toggle_alert_rule(selected_rule_id):
                            st.success("状态已切换")
                            st.rerun()

                    if deleted:
                        if delete_alert_rule(selected_rule_id):
                            st.success("已删除")
                            st.rerun()

            with tab_detail:
                st.markdown(f"**ID:** {selected_rule['id']}")
                st.markdown(f"**名称:** {selected_rule['name']}")
                st.markdown(f"**标题:** {selected_rule['title']}")
                if selected_rule.get("description"):
                    st.markdown(f"**详细描述:** {selected_rule['description']}")
                st.markdown("**WHERE 条件:**")
                st.code(selected_rule['where_clause'], language="sql")
                st.markdown(
                    f"**状态:** {'🟢 启用' if selected_rule['enabled'] else '🔴 禁用'}"
                )
                st.markdown(f"**飞书群组:** {selected_rule['feishu_group']}")
                st.markdown(f"**上次检查 ID:** {selected_rule['last_checked_id']}")
                if pd.notna(selected_rule.get("created_at")):
                    st.markdown(f"**创建时间:** {selected_rule['created_at'].strftime('%Y-%m-%d %H:%M:%S')}")
                if pd.notna(selected_rule.get("updated_at")):
                    st.markdown(f"**更新时间:** {selected_rule['updated_at'].strftime('%Y-%m-%d %H:%M:%S')}")


    # ============================================================================
    # 下方：全量规则表格 + 批量删除
    # ============================================================================
    st.divider()
    st.subheader("📊 全部规则一览")
    if not rules_df.empty:
        display_df = rules_df.copy()
        display_df["status"] = display_df["enabled"].apply(lambda x: "🟢 启用" if x else "🔴 禁用")

        selected_for_delete = checkbox_data_editor(
            display_df[["id", "name", "title", "description", "where_clause", "status",
                         "feishu_group", "last_checked_id"]],
            checkbox_label="删除",
            disabled=["id", "name", "title", "description", "where_clause", "status",
                      "feishu_group", "last_checked_id"],
            column_config_overrides={
                "id": st.column_config.NumberColumn("ID", width="small"),
                "name": st.column_config.TextColumn("规则名称", width="medium"),
                "title": st.column_config.TextColumn("告警标题", width="medium"),
                "description": st.column_config.TextColumn("描述", width="medium"),
                "where_clause": st.column_config.TextColumn("WHERE 条件", width="large"),
                "status": st.column_config.TextColumn("状态", width="small"),
                "feishu_group": st.column_config.TextColumn("飞书群组", width="small"),
                "last_checked_id": st.column_config.NumberColumn("上次检查 ID", width="small"),
            },
            key="rules_editor",
        )
        to_delete = selected_for_delete["id"].tolist()
        if to_delete:
            if st.button(f"🗑️ 删除选中的 {len(to_delete)} 条规则", type="primary",
                         width="stretch"):
                deleted_count = 0
                for rid in to_delete:
                    if delete_alert_rule(rid):
                        deleted_count += 1
                st.success(f"已删除 {deleted_count} 条规则")
                st.rerun()
    else:
        st.info("暂无规则数据")
