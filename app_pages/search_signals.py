"""Search Signals page (url_path=search_signals)."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from utils import get_cached_data
from pypinyin import lazy_pinyin, Style


def page_search_signals() -> None:
    st.set_page_config(layout="wide", page_title="Search Signals")

    # Legacy session_state keys (no writer in the new design).
    # Kept as setdefault fallbacks for any old client that still injects them.
    st.session_state.setdefault("selected_signals", [])
    st.session_state.setdefault("_is_binance_page", False)

    # 获取查询参数
    query_params = st.query_params
    exchange_param = query_params.get("exchange", [None])[0]
    signals_param = query_params.get("signals", [None])[0]
    exclude_exchange_param = query_params.get("exclude_exchange", [None])[0]

    # 设置默认值和检测逻辑
    is_review_mode = False
    preset_exchange = None
    preset_signals = None
    exclude_exchange = None

    # 根据参数设置模式
    if exchange_param:
        preset_exchange = exchange_param
        is_review_mode = True
    elif exclude_exchange_param:
        exclude_exchange = exclude_exchange_param
        is_review_mode = True
    elif signals_param:
        preset_signals = signals_param.split(',')
        is_review_mode = True

    # 根据模式和参数设置标题
    if is_review_mode:
        if preset_signals:
            st.header("📋 Key Review")
        elif preset_exchange:
            st.header(f"💱 {preset_exchange.upper()} Exchange Signals")
        else:
            st.header("📋 Today Review")
    else:
        st.header("🔍 Search Signals")

    # 快速导航按钮
    st.divider()
    st.subheader("快速导航")

    nav_col1, nav_col2 = st.columns(2)
    with nav_col1:
        if st.button("股票信号", width="stretch"):
            st.query_params.clear()
            st.query_params["exclude_exchange"] = "binance"
            st.rerun()
    with nav_col2:
        if st.button("Binance信号", width="stretch"):
            st.query_params.clear()
            st.query_params["exchange"] = "binance"
            st.rerun()

    df = get_cached_data(45)

    # Time range slider for all modes
    if 'signal_date' in df.columns:
        df['signal_date'] = pd.to_datetime(df['signal_date'])
        min_date = df['signal_date'].min().date()
        max_date = df['signal_date'].max().date()
        
        # Auto-select recent 2 days for today review mode
        # Legacy session_state flag set by review_today.py before this
        # commit removes the exec() pattern. Fall back to False if the
        # caller didn't use the new query-params path.
        st.session_state.setdefault('_auto_select_recent_2_days', False)
        auto_select_recent_2_days = st.session_state.get('_auto_select_recent_2_days', False)
        if auto_select_recent_2_days:
            valid_dates = sorted(df['signal_date'].dt.date.unique(), reverse=True)
            if len(valid_dates) >= 2:
                default_range = (valid_dates[1], valid_dates[0])
            elif len(valid_dates) == 1:
                default_range = (valid_dates[0], valid_dates[0])
            else:
                default_range = (min_date, max_date)
        else:
            default_range = (min_date, max_date)
        
        date_range = st.slider(
            "Select signal date range",
            min_value=min_date,
            max_value=max_date,
            value=default_range,
            format="YYYY-MM-DD"
        )
        
        # Filter dataframe based on selected date range
        df = df[(df['signal_date'].dt.date >= date_range[0]) & (df['signal_date'].dt.date <= date_range[1])].copy()
        
        st.info(f"Showing signals from {date_range[0]} to {date_range[1]}")

    if preset_exchange and 'exchange' in df.columns:
        st.info(f"Auto-selected Exchange: {preset_exchange}")
        df = df[df['exchange'] == preset_exchange]

    if exclude_exchange and 'exchange' in df.columns:
        st.info(f"Excluded Exchange: {exclude_exchange}")
        df = df[df['exchange'] != exclude_exchange]

    if preset_signals and 'signal_name' in df.columns:
        st.info(f"Auto-selected Signals: {', '.join(preset_signals)}")
        df = df[df['signal_name'].isin(preset_signals)]

    # Create two columns for layout
    col1, col2 = st.columns([3, 1])

    with col1:
        # Get unique symbols and names for the dropdown
        symbol_options = []
        for idx, row in df[['symbol', 'symbol_name']].drop_duplicates().iterrows():
            symbol = str(row['symbol'])
            symbol_name = str(row['symbol_name'])
            if symbol and symbol_name:
                # Create option with pinyin for enhanced search
                try:
                    pinyin_initials = ''.join([lazy_pinyin(char, style=Style.FIRST_LETTER)[0] for char in symbol_name if char.strip()])
                    if pinyin_initials and pinyin_initials.lower() != symbol.lower():
                        # Add option with pinyin appended for search capability
                        option = f"{symbol} - {symbol_name} {pinyin_initials}"
                    else:
                        option = f"{symbol} - {symbol_name}"
                except:
                    option = f"{symbol} - {symbol_name}"
                symbol_options.append(option)
            elif symbol:
                option = symbol
                symbol_options.append(option)
            else:
                continue
        symbol_options = sorted(set(symbol_options))  # Remove duplicates and sort

        # Add an empty option at the beginning for default selection
        symbol_options = [""] + symbol_options

        # Use a single selectbox with built-in filtering capability
        selected_option = st.selectbox(
            "Enter symbol to search",
            options=symbol_options,
            placeholder="e.g., AAPL, TSLA, MSFT...",
            help="Supports exact match, partial match, wildcards (*, ?), and multiple symbols (comma-separated)"
        )

        # Extract the symbol from the selected option
        if selected_option and selected_option != "":
            symbol_search = selected_option.split(" - ")[0] if " - " in selected_option else selected_option
        else:
            symbol_search = ""

    with col2:
        st.write(" ")  # Empty space to maintain layout

    # Filter data based on symbol search
    if symbol_search:
        # Process symbol search to handle multiple symbols and wildcards
        symbol_search_processed = symbol_search.strip()

        # Split by comma to handle multiple symbols
        search_terms = [term.strip() for term in symbol_search_processed.split(',')]

        # Create a mask for filtering
        mask = pd.Series([False] * len(df), dtype=bool)

        for term in search_terms:
            term = term.strip()
            if not term:
                continue

            # Check if the term contains wildcard characters
            if '*' in term or '?' in term or '[' in term or ']' in term:
                # Handle wildcard matching using regex
                # Convert wildcard pattern to regex pattern
                regex_pattern = term.replace('*', '.*').replace('?', '.')
                mask |= df['symbol'].str.contains(regex_pattern, case=False, regex=True, na=False)
            else:
                # Case-insensitive exact match for regular terms
                mask |= df['symbol'].str.lower() == term.lower()

        filtered_df = df[mask]
    else:
        filtered_df = df

    # Apply shared signal selection filter if available
    if 'selected_signals' in st.session_state and st.session_state['selected_signals']:
        filtered_df = filtered_df[filtered_df["signal_name"].isin(st.session_state['selected_signals'])]

    # Add date range filter
    if not is_review_mode and 'signal_date' in filtered_df.columns:
        filtered_df['signal_date'] = pd.to_datetime(filtered_df['signal_date'])
        min_date = filtered_df['signal_date'].min().date()
        max_date = filtered_df['signal_date'].max().date()
        
        st.subheader("Time Range Filter")
        date_range = st.date_input(
            "Select date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            format="YYYY-MM-DD"
        )
        
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            filtered_df = filtered_df[
                (filtered_df['signal_date'].dt.date >= start_date) & 
                (filtered_df['signal_date'].dt.date <= end_date)
            ]

    # Add additional filters
    col1, col2, col3 = st.columns(3)

    with col1:
        # Exchange filter
        exchange_options = ['All'] + sorted(df['exchange'].dropna().unique().tolist())
        default_exchange_index = 0
        if preset_exchange and preset_exchange in exchange_options:
            default_exchange_index = exchange_options.index(preset_exchange)
        selected_exchange = st.selectbox("Filter by Exchange", options=exchange_options, index=default_exchange_index)

        if selected_exchange != 'All':
            filtered_df = filtered_df[filtered_df['exchange'] == selected_exchange]

    with col2:
        # Signal name filter
        if 'signal_name' in df.columns:
            signal_options = ['All'] + sorted(df['signal_name'].dropna().unique().tolist())
            default_index = 0
            if preset_signals:
                if len(preset_signals) == 1 and preset_signals[0] in signal_options:
                    default_index = signal_options.index(preset_signals[0])
            selected_signal = st.selectbox("Filter by Signal Name", options=signal_options, index=default_index)

            if selected_signal != 'All':
                filtered_df = filtered_df[filtered_df['signal_name'] == selected_signal]

    with col3:
        # Frequency filter
        if 'freq' in df.columns:
            freq_options = ['All'] + sorted(df['freq'].dropna().unique().tolist())
            selected_freq = st.selectbox("Filter by Frequency", options=freq_options, index=0)

            if selected_freq != 'All':
                filtered_df = filtered_df[filtered_df['freq'] == selected_freq]

    # Display results header after all filters
    if symbol_search:
        st.subheader(f"Search Results for '{symbol_search}'")
        st.write(f"Found **{filtered_df['symbol'].nunique()}** unique symbols | **{len(filtered_df)}** signal records")
    else:
        st.subheader("All Signals")
        st.write(f"Showing **{filtered_df['symbol'].nunique()}** unique symbols | **{len(filtered_df)}** total signal records")

    # Show results
    if filtered_df.empty:
        st.info("No signals found matching your search criteria.")
        st.stop()

    # Add view mode selection
    view_mode = st.radio(
        "View mode",
        options=["Compact", "Detail"],
        index=0,
        horizontal=True
    )

    if view_mode == "Detail":
        # Select columns to display - prioritize symbol and symbol_name
        display_columns = [
            'symbol', 'symbol_name', 'symbol_id', 'exchange', 'signal_name',
            'signal_date', 'freq', 'price', 'score', 'reason'
        ]

        # Only include columns that exist in the dataframe
        available_columns = [col for col in display_columns if col in filtered_df.columns]

        # Sort by signal date (most recent first)
        filtered_df_sorted = filtered_df.sort_values('signal_date', ascending=False)

        # Create a combined symbol display
        # Create a combined column that shows both symbol and name for better readability
        filtered_df_sorted['_display_symbol'] = filtered_df_sorted.apply(
            lambda row: f"{row['symbol']} - {row['symbol_name']}", axis=1
        )
        # If we want to show the combined column instead of separate ones
        display_cols = []
        for col in available_columns:
            if col == 'symbol':
                # Add the combined column first
                display_cols.append('_display_symbol')
            elif col != 'symbol_name':  # Skip symbol_name since it's in the combined column
                display_cols.append(col)
        display_df = filtered_df_sorted[display_cols]

        # Display the dataframe
        st.dataframe(
            display_df,
            height=600,
            width="stretch"
        )
    else:
        # Grouped view by symbol and signal_name
        # Fill NaN and empty strings to avoid groupby dropping them
        filtered_df_filled = filtered_df.copy()
        filtered_df_filled['exchange'] = filtered_df_filled['exchange'].replace('', pd.NA).fillna('(No Exchange)')
        filtered_df_filled['symbol'] = filtered_df_filled['symbol'].replace('', pd.NA).fillna('(No Symbol)')
        filtered_df_filled['signal_name'] = filtered_df_filled['signal_name'].replace('', pd.NA).fillna('(No Signal)')
        
        grouped_df = filtered_df_filled.sort_values('signal_date', ascending=False).groupby(['exchange', 'symbol', 'signal_name'], as_index=False).apply(
            lambda group: pd.Series({
                'symbol_name': group['symbol_name'].iloc[0] if 'symbol_name' in group.columns else '',
                'count': len(group),
                'signal_info': '\n'.join([
                    f"{row['signal_date'].strftime('%Y-%m-%d %H:%M:%S') if pd.notna(row['signal_date']) else 'N/A'} | "
                    f"Freq: {row['freq'] if 'freq' in group.columns and pd.notna(row['freq']) else 'N/A'} | "
                    f"Price: {row['price'] if 'price' in group.columns and pd.notna(row['price']) else 'N/A'} | "
                    f"Score: {row['score'] if 'score' in group.columns and pd.notna(row['score']) else 'N/A'}"
                    for _, row in group.iterrows()
                ])
            }), include_groups=False
        )
        
        # Reorder columns
        column_order = ['exchange', 'symbol', 'symbol_name', 'signal_name', 'count', 'signal_info']
        available_cols = [c for c in column_order if c in grouped_df.columns]
        grouped_df = grouped_df[available_cols]
        
        st.dataframe(
            grouped_df,
            height=600,
            width='stretch',
            hide_index=True
        )
