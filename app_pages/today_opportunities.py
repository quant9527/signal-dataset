"""Today Opportunities page (url_path=today_opportunities)."""
from __future__ import annotations

from datetime import timedelta

import altair as alt
import pandas as pd

import streamlit as st

from data import get_sector_constituents_from_db
from utils import get_cached_data


def calculate_signal_score(
    row: pd.Series,
    all_signals_df: pd.DataFrame,
    today: pd.Timestamp,
    sector_data: dict | None = None,
) -> int:
    """Compute a 0-100 quality score for a single signal row.

    Scoring dimensions:
    - Signal-type base score (10-30 points)
    - Time freshness (today +20, day-1 +15, day-2 +10, decay after)
    - Multi-signal resonance (+15 to +30)
    - Recent signal frequency (+8 to +15)
    - Sector heat (+10 to +20)
    """
    score = 0
    signal_date = pd.to_datetime(row['signal_date'])
    symbol = row['symbol']
    signal_name = row['signal_name']

    signal_weights = {
        'cmp_rebound_pioneer_ma5ma10': 30,
        'cmp_rebound_pioneer_macd': 28,
        'cmp_zs_macd': 25,
        'cmp_zs_ma5ma10': 25,
        'cmp_xsx_ma5ma10': 20,
        'cmp_xsx_macd': 20,
        'cmp_break_ma5ma10': 22,
        'cmp_break_macd': 22,
        'active_vol': 15,
        'nested_2bc_ma5ma10_': 18,
        'nested_2bc_macd_': 18,
        'cl3b_zsx': 20,
    }

    base_score = 10
    for prefix, weight in signal_weights.items():
        if str(signal_name).startswith(prefix):
            base_score = weight
            break
    score += base_score

    days_diff = (today - signal_date).days
    if days_diff == 0:
        score += 20
    elif days_diff == 1:
        score += 15
    elif days_diff == 2:
        score += 10
    else:
        score += max(0, 5 - days_diff)

    symbol_signals = all_signals_df[all_signals_df['symbol'] == symbol]
    unique_signals = symbol_signals['signal_name'].nunique()
    if unique_signals >= 3:
        score += 30
    elif unique_signals == 2:
        score += 20
    elif unique_signals == 1:
        score += 10

    recent_signals = symbol_signals[
        symbol_signals['signal_date'] >= today - timedelta(days=5)
    ]
    if len(recent_signals) >= 3:
        score += 15
    elif len(recent_signals) == 2:
        score += 8

    if sector_data and symbol in sector_data:
        sector_signals = sector_data[symbol]
        if sector_signals >= 5:
            score += 20
        elif sector_signals >= 3:
            score += 15
        elif sector_signals >= 2:
            score += 10

    return min(100, score)


def page_today_opportunities() -> None:
    """Today Opportunities radar (url_path=today_opportunities)."""
    st.set_page_config(layout="wide", page_title="Today Opportunities")
    st.header("🎯 今日机会雷达")

    df = get_cached_data(45)

    if df.empty:
        st.warning("暂无数据")
        st.stop()

    df['signal_date'] = pd.to_datetime(df['signal_date'])

    latest_date = df['signal_date'].max().date()
    today = pd.Timestamp(latest_date)

    st.markdown(f"### 📅 分析日期：{latest_date}")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        show_only_today = st.toggle(
            "只看今日新增", value=True,
            help="只显示今天首次出现的信号",
        )
    with col2:
        min_score = st.slider(
            "最低评分", min_value=0, max_value=100, value=40, step=5,
            help="只显示高于此分数的机会",
        )
    with col3:
        quick_filter = st.segmented_control(
            "快速筛选",
            options=["全部", "高分(70+)", "共振", "反弹先锋", "放量突破"],
            default="全部",
        )

    if quick_filter == "高分(70+)":
        min_score = max(min_score, 70)
        show_only_today = False
    elif quick_filter == "共振":
        show_only_today = False
    elif quick_filter == "反弹先锋":
        show_only_today = True
    elif quick_filter == "放量突破":
        show_only_today = True

    if show_only_today:
        filtered_df = df[df['signal_date'].dt.date == latest_date].copy()
    else:
        filtered_df = df[df['signal_date'] >= today - timedelta(days=3)].copy()

    if filtered_df.empty:
        st.warning(f"📭 {'今日' if show_only_today else '近3日'}暂无信号数据")
        st.stop()

    sector_df = filtered_df[filtered_df['exchange'] == 'ths']
    sector_signal_counts = (
        sector_df.groupby('symbol').size().to_dict() if not sector_df.empty else {}
    )

    st.markdown("### 🔍 正在分析信号质量...")

    scored_data = []
    for idx, row in filtered_df.iterrows():
        score = calculate_signal_score(row, filtered_df, today, sector_signal_counts)
        scored_data.append({
            **row.to_dict(),
            'score': score,
            'score_level': (
                '🔥' if score >= 80
                else '⚡' if score >= 60
                else '📊' if score >= 40
                else '💤'
            ),
        })

    scored_df = pd.DataFrame(scored_data)
    scored_df = scored_df.sort_values(
        ['score', 'signal_date'], ascending=[False, False]
    )
    scored_df = scored_df[scored_df['score'] >= min_score]

    if scored_df.empty:
        st.warning(f"📭 没有评分高于 {min_score} 分的信号")
        st.stop()

    st.divider()
    st.markdown("### 📊 核心指标")

    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("总信号数", len(scored_df))
    with col2:
        today_signals = len(scored_df[scored_df['signal_date'].dt.date == latest_date])
        st.metric(
            "今日新增", today_signals,
            delta=f"+{today_signals}" if today_signals > 0 else None,
        )
    with col3:
        high_score = len(scored_df[scored_df['score'] >= 70])
        st.metric("高分机会(70+)", high_score)
    with col4:
        multi_signal_symbols = (
            scored_df.groupby('symbol').filter(lambda x: len(x) >= 2)['symbol']
            .nunique()
        )
        st.metric("共振标的", multi_signal_symbols)
    with col5:
        avg_score = int(scored_df['score'].mean())
        st.metric("平均评分", f"{avg_score}分")

    st.divider()
    st.markdown("### 🎯 今日Top机会 (按评分排序)")

    display_df = scored_df.head(20).copy()
    symbol_groups = display_df.groupby('symbol')

    for symbol, group in list(symbol_groups)[:10]:
        row = group.iloc[0]
        symbol_name = row.get('symbol_name', symbol)
        exchange = row.get('exchange', '')
        score = int(row['score'])

        if score >= 80:
            priority = "🚨 URGENT"
            border_color = "#ff4b4b"
        elif score >= 60:
            priority = "⚡ HIGH"
            border_color = "#ffa726"
        else:
            priority = "📊 NORMAL"
            border_color = "#66bb6a"

        all_signals = group['signal_name'].tolist()
        signal_badges = ' '.join([f"`{s}`" for s in all_signals[:3]])
        if len(all_signals) > 3:
            signal_badges += f" +{len(all_signals)-3} more"

        latest_signal = (
            group['signal_date'].max().strftime('%m-%d %H:%M')
            if len(group) > 0 else ''
        )

        with st.container():
            st.markdown(f"""
<div style="border-left: 4px solid {border_color}; padding-left: 10px; margin: 10px 0;">
    <h4>{priority} | {symbol} {symbol_name} <span style="color:{border_color};font-size:1.2em">{score}分</span></h4>
    <p><strong>信号:</strong> {signal_badges}</p>
    <p><small>交易所: {exchange} | 最新: {latest_signal}</small></p>
</div>
""", unsafe_allow_html=True)

            with st.expander(f"查看 {symbol} 详情", expanded=False):
                detail_cols = ['signal_date', 'signal_name', 'exchange', 'score']
                detail_df = group[detail_cols].copy()
                detail_df['signal_date'] = detail_df['signal_date'].dt.strftime('%Y-%m-%d %H:%M')
                detail_df['score'] = detail_df['score'].astype(int)
                st.dataframe(detail_df, hide_index=True, width="stretch")

                if exchange == 'ths':
                    constituents = get_sector_constituents_from_db(symbol, 'ths')
                    if constituents:
                        st.markdown(f"**成分股 ({len(constituents)}只):**")
                        constituent_signals = df[
                            (df['symbol'].isin(constituents))
                            & (df['signal_date'] >= today - timedelta(days=3))
                        ]
                        if not constituent_signals.empty:
                            st.dataframe(
                                constituent_signals[
                                    ['symbol', 'symbol_name', 'signal_name', 'signal_date']
                                ].head(10),
                                hide_index=True,
                            )
                        else:
                            st.info("成分股近3日暂无信号")

    st.divider()
    st.markdown("### 🔥 板块热度排行")

    if sector_df.empty:
        st.info("暂无板块信号")
    else:
        sector_stats = sector_df.groupby('symbol').agg({
            'signal_name': 'count',
            'symbol_name': 'first',
            'signal_date': 'max',
        }).reset_index()
        sector_stats.columns = ['symbol', 'signal_count', 'name', 'latest_signal']
        sector_stats = sector_stats.sort_values('signal_count', ascending=False).head(10)

        chart_data = sector_stats.copy()
        chart_data['display'] = chart_data['symbol'] + ' ' + chart_data['name']

        chart = alt.Chart(chart_data).mark_bar().encode(
            x=alt.X('signal_count:Q', title='信号数量'),
            y=alt.Y('display:N', title='板块', sort='-x'),
            color=alt.Color(
                'signal_count:Q', scale=alt.Scale(scheme='oranges'), title='热度'
            ),
            tooltip=['symbol', 'name', 'signal_count', 'latest_signal'],
        ).properties(height=300)

        st.altair_chart(chart, width="stretch")

    st.divider()
    st.markdown("### 📈 信号类型分布")

    signal_dist = scored_df['signal_name'].value_counts().head(15)
    dist_df = signal_dist.reset_index()
    dist_df.columns = ['signal_name', 'count']

    dist_chart = alt.Chart(dist_df).mark_bar().encode(
        x=alt.X('count:Q', title='出现次数'),
        y=alt.Y('signal_name:N', title='信号类型', sort='-x'),
        color=alt.Color(
            'count:Q', scale=alt.Scale(scheme='blues'), title='次数'
        ),
        tooltip=['signal_name', 'count'],
    ).properties(height=400)

    st.altair_chart(dist_chart, width="stretch")

    st.divider()
    with st.expander("📥 下载完整数据", expanded=False):
        download_df = scored_df[
            ['symbol', 'symbol_name', 'signal_name', 'signal_date', 'score', 'exchange']
        ].copy()
        download_df['signal_date'] = download_df['signal_date'].dt.strftime('%Y-%m-%d')
        download_df['score'] = download_df['score'].astype(int)

        csv = download_df.to_csv(index=False)
        st.download_button(
            label="下载CSV",
            data=csv,
            file_name=f"today_opportunities_{latest_date}.csv",
            mime="text/csv",
        )

        st.dataframe(
            download_df, hide_index=True, width="stretch", height=400
        )