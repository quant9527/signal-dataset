from typing import Any
from urllib.parse import quote

import pandas as pd
import streamlit as st

from constants import KLINE_DEFAULT_FREQ
from symbol_picker import encode_symbol_token


# ============================================================================
# 周期排序（从大到小）
# ============================================================================
FREQ_ORDER = ['1M', '1w', '1d', '2h', '1h', '30m', '15m', '5m', '1m']


# ============================================================================
# K 线入口 URL 生成
# ============================================================================
def build_kline_link_url(
    exchange: str | None,
    symbol: str | None,
    freq: str | None = KLINE_DEFAULT_FREQ,
) -> str:
    """构造指向 K 线页的相对 URL: ``/kline?symbol=<token>``。

    复用 :func:`symbol_picker.encode_symbol_token` 编码 token；
    exchange 或 symbol 缺失或为 ``(No Exchange)`` / ``(No Symbol)`` 占位符时
    返回空串（不生成可点击链接）。
    """
    ex = str(exchange or "").strip().lower()
    sym = str(symbol or "").strip()
    if not ex or not sym:
        return ""
    if ex.casefold() == "(no exchange)" or sym.casefold() == "(no symbol)":
        return ""
    token = encode_symbol_token(ex, sym, freq)
    return f"/kline?symbol={quote(token, safe=':')}"


def sort_freqs(freqs: list[str]) -> list[str]:
    """
    按照标准周期顺序排序（从大到小）：1M > 1w > 1d > 2h > 1h > 30m > 15m > 5m > 1m
    未知周期排在最后
    """
    def get_order(freq):
        try:
            return FREQ_ORDER.index(freq)
        except ValueError:
            return len(FREQ_ORDER)  # 未知周期排在最后
    
    return sorted(freqs, key=get_order)


def normalize_signal_date_field(df, col: str = 'signal_date', tz: str = 'Asia/Shanghai'):
    """Normalize a date-like column to timezone `tz` (UTC+8) and return as tz-naive local datetimes.

    Handles numeric unix timestamps (seconds or milliseconds) and string date representations.
    The result will be timezone-local (Asia/Shanghai) and tz-naive datetimes.
    
    注意：
    - 数字类型（unix timestamp）假设是 UTC，会转换为目标时区
    - 字符串/datetime 如果有时区信息，会转换为目标时区
    - 字符串/datetime 如果没有时区信息，假设已经是目标时区，不做转换
    """
    if col not in df.columns:
        return df

    s = df[col]
    
    try:
        if pd.api.types.is_numeric_dtype(s):
            # 数字类型（unix timestamp）假设是 UTC
            if s.dropna().abs().gt(1e12).any():
                s_dt = pd.to_datetime(s, unit='ms', errors='coerce', utc=True)
            else:
                s_dt = pd.to_datetime(s, unit='s', errors='coerce', utc=True)
            # 转换为目标时区
            s_local = s_dt.dt.tz_convert(tz)
            s_local_str = s_local.dt.strftime("%Y-%m-%d %H:%M:%S")
            df[col] = pd.to_datetime(s_local_str, errors='coerce')
        else:
            # 非数字类型，先尝试解析
            s_dt = pd.to_datetime(s, errors='coerce')
            
            # 检查是否有时区信息
            if s_dt.dt.tz is not None:
                # 有时区信息，转换为目标时区
                s_local = s_dt.dt.tz_convert(tz)
                s_local_str = s_local.dt.strftime("%Y-%m-%d %H:%M:%S")
                df[col] = pd.to_datetime(s_local_str, errors='coerce')
            else:
                # 没有时区信息，假设已经是目标时区（东八区），直接使用
                df[col] = s_dt
    except Exception:
        # 兜底：直接解析，不做时区转换
        df[col] = pd.to_datetime(s, errors='coerce')

    return df


# ============================================================================
# Compact 模式显示函数
# ============================================================================
def display_signals_compact(
    df: pd.DataFrame,
    group_by_cols: list[str] = ['exchange', 'symbol', 'signal_name'],
    include_freq: bool = True,
    height: int = 600,
    title: str = None,
    link_freq: str | None = None,
) -> None:
    """
    以 Compact 模式显示信号数据

    Args:
        df: 信号数据 DataFrame
        group_by_cols: 分组依据的列
        include_freq: 是否在 signal_info 中包含 freq
        height: dataframe 显示高度
        title: 可选的标题，显示在数据表上方
        link_freq: 用于生成每行 K 线入口 URL 的周期；为 None 时不渲染 K 线列。
            复用 :func:`symbol_picker.encode_symbol_token`，目标路由
            ``/kline?symbol=exchange:symbol:freq``。
    """
    if df.empty:
        st.info("暂无数据")
        return

    # 填充空值
    df_filled = df.copy()
    df_filled['exchange'] = df_filled['exchange'].replace('', pd.NA).fillna('(No Exchange)')
    df_filled['symbol'] = df_filled['symbol'].replace('', pd.NA).fillna('(No Symbol)')
    if 'signal_name' in group_by_cols:
        df_filled['signal_name'] = df_filled['signal_name'].replace('', pd.NA).fillna('(No Signal)')

    # 创建组合显示字段：exchange:symbol-symbol_name (如 as:000001-平安银行)
    if 'symbol' in df_filled.columns and 'symbol_name' in df_filled.columns:
        df_filled['_display_symbol'] = df_filled.apply(
            lambda row: f"{row['exchange']}:{row['symbol']}-{row['symbol_name']}"
                if pd.notna(row['symbol_name']) and row['symbol_name']
                else f"{row['exchange']}:{row['symbol']}",
            axis=1
        )

    # 构建 signal_info 内容
    # 如果 signal_name 不在分组列中，需要在每行显示 signal_name
    include_signal_name = 'signal_name' not in group_by_cols

    def build_signal_info(group):
        lines = []
        for _, row in group.iterrows():
            dt = row.get('signal_date')
            date_str = dt.strftime('%Y-%m-%d %H:%M:%S') if pd.notna(dt) else 'N/A'
            parts = [date_str]
            # 如果 signal_name 不在分组列中，显示 signal_name
            if include_signal_name and 'signal_name' in group.columns:
                parts.append(f"{row['signal_name'] if pd.notna(row.get('signal_name')) else 'N/A'}")
            if include_freq and 'freq' in group.columns:
                parts.append(f"Freq: {row['freq'] if pd.notna(row.get('freq')) else 'N/A'}")
            if 'price' in group.columns:
                parts.append(f"Price: {row['price'] if pd.notna(row.get('price')) else 'N/A'}")
            if 'score' in group.columns:
                parts.append(f"Score: {row['score'] if pd.notna(row.get('score')) else 'N/A'}")
            lines.append(' | '.join(parts))
        return '\n'.join(lines)

    # 分组聚合
    df_sorted = df_filled.sort_values('signal_date', ascending=False)

    # 使用 agg 替代 apply，更稳定
    grouped_df = df_sorted.groupby(group_by_cols, as_index=False).agg(
        symbol_name=('symbol_name', 'first'),
        count=('symbol', 'size'),
        _latest_date=('signal_date', 'max'),
    )

    # 构建每行 K 线入口 URL（复用 symbol_picker.encode_symbol_token）
    if {'exchange', 'symbol'}.issubset(grouped_df.columns):
        if link_freq is not None:
            grouped_df['_kline_url'] = grouped_df.apply(
                lambda r: build_kline_link_url(r['exchange'], r['symbol'], link_freq),
                axis=1,
            )
        else:
            # 每行使用该分组中最新一条信号的 freq；无效或缺失时退回默认。
            if 'freq' in df_sorted.columns:
                latest_freq = (
                    df_sorted.sort_values('signal_date', ascending=False)
                    .dropna(subset=['freq'])
                    .drop_duplicates(subset=group_by_cols, keep='first')
                    .set_index(group_by_cols)['freq']
                )
            else:
                latest_freq = pd.Series(dtype=object)

            def _lookup(row: pd.Series) -> str | None:
                key = tuple(row[c] for c in group_by_cols)
                if key in latest_freq.index:
                    val = latest_freq.loc[key]
                    if isinstance(val, pd.Series):
                        val = val.iloc[0]
                    return val
                return None

            row_freqs: list[str | None] = [
                _lookup(row) for _, row in grouped_df.iterrows()
            ]
            grouped_df = grouped_df.assign(_row_freq=row_freqs)

            def _row_url(r: pd.Series) -> str:
                freq_val = r.get('_row_freq')
                if freq_val is None or (isinstance(freq_val, float) and pd.isna(freq_val)):
                    freq_val = KLINE_DEFAULT_FREQ
                return build_kline_link_url(r['exchange'], r['symbol'], freq_val)

            grouped_df['_kline_url'] = grouped_df.apply(_row_url, axis=1)
            grouped_df = grouped_df.drop(columns=['_row_freq'])
    else:
        grouped_df['_kline_url'] = ''

    # 单独计算 signal_info（需要访问多列）
    signal_info_dict = {}
    for keys, group in df_sorted.groupby(group_by_cols):
        key = keys if isinstance(keys, tuple) else (keys,)
        signal_info_dict[key] = build_signal_info(group)

    # 将 signal_info 合并到 grouped_df
    grouped_df['signal_info'] = grouped_df.apply(
        lambda row: signal_info_dict.get(tuple(row[col] for col in group_by_cols), ''),
        axis=1
    )

    # 按最新信号时间降序排序
    grouped_df = grouped_df.sort_values('_latest_date', ascending=False)

    # 检查是否为空
    if grouped_df.empty:
        st.warning("分组后数据为空")
        return

    # 确定显示列
    if '_display_symbol' in df_filled.columns:
        # 合并 _display_symbol
        merge_cols = group_by_cols + ['_display_symbol']
        grouped_df = grouped_df.merge(
            df_filled[merge_cols].drop_duplicates(),
            on=group_by_cols,
            how='left'
        )
        # 构建列顺序：用 _display_symbol 替换 exchange+symbol（已合并）
        column_order = ['_display_symbol']
        for col in group_by_cols:
            if col not in ['exchange', 'symbol']:  # 跳过已合并的列
                column_order.append(col)
        column_order.extend(['count', 'signal_info', '_kline_url'])
    else:
        column_order = group_by_cols + ['symbol_name', 'count', 'signal_info', '_kline_url']

    available_cols = [c for c in column_order if c in grouped_df.columns]

    # 配置 K 线入口列（LinkColumn）：当至少有一行存在有效 URL 时启用。
    # Streamlit 1.59 的 LinkColumn 没有 url_col 参数；这里把 URL 直接放在数据列
    # 自身（该列已是字符串），并通过 display_text 渲染为可点击的固定文字。
    column_config: dict[str, Any] | None = None
    if (grouped_df['_kline_url'] != '').any():
        column_config = {
            '_kline_url': st.column_config.LinkColumn(
                '📈 K线',
                display_text='K线 →',
                help='打开对应 K 线页（/kline?symbol=...）',
                width='small',
            ),
        }

    # 显示标题
    if title:
        st.write(title)

    st.dataframe(
        grouped_df[available_cols],
        height=height,
        width='stretch',
        hide_index=True,
        column_config=column_config,
    )


# ============================================================================
# 多视图模式显示函数
# ============================================================================
def display_signals_multiview(
    df: pd.DataFrame,
    height: int = 500,
    show_stats: bool = True,
    freq_col: str = 'freq',
) -> None:
    """
    以多视图模式显示信号数据（Symbol优先 + 信号优先 + 按周期分别显示）
    
    Args:
        df: 信号数据 DataFrame
        height: dataframe 显示高度
        show_stats: 是否显示统计信息
        freq_col: 周期列名
    """
    if df.empty:
        st.info("暂无数据")
        return
    
    # 显示统计信息
    if show_stats:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("📊 标的数量", df['symbol'].nunique())
        with col2:
            st.metric("📈 信号总数", len(df))
    
    # 获取可用周期
    available_freqs = []
    if freq_col in df.columns:
        available_freqs = sort_freqs(df[freq_col].dropna().unique().tolist())
    
    # 构建 tabs：Symbol优先 + 信号优先 + 各周期
    tab_names = ["📊 Symbol优先", "📋 信号优先"] + [f"⏱️ {freq}" for freq in available_freqs]
    tabs = st.tabs(tab_names)
    
    # Symbol优先：以 symbol 为单位分组
    with tabs[0]:
        display_signals_compact(
            df,
            group_by_cols=['exchange', 'symbol'],
            include_freq=True,
            height=height,
        )
    
    # 信号优先：按 signal_name 分组
    with tabs[1]:
        display_signals_compact(
            df,
            group_by_cols=['exchange', 'symbol', 'signal_name'],
            include_freq=True,
            height=height,
        )
    
    # 按周期分别显示
    for i, freq in enumerate(available_freqs):
        with tabs[i + 2]:
            freq_df = df[df[freq_col] == freq].copy()
            if freq_df.empty:
                st.info(f"暂无 {freq} 周期的信号")
            else:
                st.write(f"**{freq} 周期信号数：{len(freq_df)}，涉及 {freq_df['symbol'].nunique()} 个标的**")
                display_signals_compact(
                    freq_df,
                    group_by_cols=['exchange', 'symbol', 'signal_name'],
                    include_freq=False,
                    height=height,
                    link_freq=freq,
                )


# ============================================================================
# 通用 Instrument 搜索选择器（复用组件）
# ============================================================================
from data import search_instruments  # noqa: E402


@st.cache_data(ttl=300)
def get_cached_data(
    time_window_days: int = 30,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    signal_name_prefix: str | None = None,
    signal_not: str | None = None,
) -> pd.DataFrame:
    """
    Load signals with caching. Same parameters as load_data but cached within
    a Streamlit session to avoid redundant DB calls on re-renders.
    """
    from data import load_data
    return load_data(
        time_window_days=time_window_days,
        start_date=start_date,
        end_date=end_date,
        signal_name_prefix=signal_name_prefix,
        signal_not=signal_not,
    )


def checkbox_data_editor(
    df: pd.DataFrame,
    *,
    checkbox_label: str = "选择",
    disabled: list[str] | None = None,
    column_config_overrides: dict[str, Any] | None = None,
    key: str,
) -> pd.DataFrame:
    """
    Show a read-only DataFrame with a checkbox column for row selection.

    Returns a DataFrame containing only the rows where the checkbox was True,
    with the checkbox column removed. Returns empty DataFrame if none selected.
    """
    data = df.copy()
    data[checkbox_label] = False
    all_cols = {col: st.column_config.TextColumn(col, disabled=True) for col in df.columns}
    if column_config_overrides:
        all_cols.update(column_config_overrides)
    all_cols[checkbox_label] = st.column_config.CheckboxColumn(checkbox_label, default=False)
    edited = st.data_editor(
        data,
        hide_index=True,
        width="stretch",
        column_config=all_cols,
        disabled=[*[c for c in (disabled or []) if c in df.columns]],
        key=key,
    )
    selected = edited[edited[checkbox_label]]
    return selected[[c for c in selected.columns if c != checkbox_label]]


def instrument_search_picker(
    key_prefix: str = "search",
    limit: int = 100,
) -> pd.DataFrame:
    """
    通用 Instrument 搜索+多选组件。

    返回用户勾选选中的 instrument 行 DataFrame（含 exchange, symbol, name, sub_exchange）。
    未选择时返回空 DataFrame。

    Args:
        key_prefix: Streamlit widget key 前缀，避免同一页多个实例冲突
        limit: 单次搜索返回上限
    """
    query = st.text_input(
        "搜索代码、名称或别名",
        placeholder="输入代码、名称或别名关键字",
        key=f"{key_prefix}_query",
    )

    if not query.strip():
        return pd.DataFrame()

    results = search_instruments(query.strip(), limit=limit)
    if results.empty:
        st.info("未找到匹配的标的")
        return pd.DataFrame()

    st.write(f"找到 {len(results)} 个结果")
    cols_to_disable = ["exchange", "symbol", "name", "alias", "sub_exchange"]
    selected = checkbox_data_editor(
        results,
        checkbox_label="选择",
        disabled=cols_to_disable,
        key=f"{key_prefix}_editor",
    )
    return selected
