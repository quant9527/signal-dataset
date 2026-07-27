import os
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st


def create_all_signals_columns(display_df, full_df, include_extra_info=False):
    """
    Create all_signals and all_signals_count columns for a dataframe.

    Args:
        display_df: Dataframe with records to display (e.g., latest records per symbol)
        full_df: Full dataframe containing all signals to be aggregated
        include_extra_info: Whether to include additional info like freq and price

    Returns:
        tuple: (updated_display_df with all_signals and all_signals_count columns)
    """
    if not full_df.empty and "signal_name" in full_df.columns and "signal_date" in full_df.columns:
        # Sort the full dataframe by symbol and signal_date for chronological display
        df_sorted = full_df.sort_values(["symbol", "signal_date"], ascending=[True, False])

        # Include signal_name, signal_date, and freq in the all_signals column（按 signal_name+signal_date+freq 去重，避免重复行刷屏）
        def format_signals(group):
            key_cols = ["signal_name", "signal_date"]
            if "freq" in group.columns:
                key_cols.append("freq")
            group = group.drop_duplicates(subset=key_cols)
            rows = []
            for _, row in group.iterrows():
                # Format signal_date to be more readable
                signal_date = row["signal_date"].strftime("%Y-%m-%d %H:%M:%S") if pd.notna(row["signal_date"]) else str(row["signal_date"])
                signal_info = f"{row['signal_name']} | {signal_date}"
                if not include_extra_info and 'freq' in group.columns and pd.notna(row.get('freq')):
                    signal_info += f" | {row['freq']}"
                if include_extra_info and 'freq' in group.columns and pd.notna(row.get('freq')):
                    signal_info += f" | Freq: {row['freq']}"
                if include_extra_info and 'price' in group.columns and pd.notna(row.get('price')):
                    signal_info += f" | Price: {row['price']}"
                rows.append(signal_info)
            return "\n".join(rows)

        symbol_signals = df_sorted.groupby("symbol").apply(format_signals, include_groups=False).to_dict()
        # 去重后的条数作为 all_signals_count
        def count_unique_signals(group):
            key_cols = ["signal_name", "signal_date"]
            if "freq" in group.columns:
                key_cols.append("freq")
            return group.drop_duplicates(subset=key_cols).shape[0]
        symbol_signal_counts = df_sorted.groupby("symbol").apply(count_unique_signals, include_groups=False).to_dict()

        # Add the all_signals column to display_df
        display_df["all_signals"] = display_df["symbol"].map(symbol_signals).apply(lambda x: x if x is not None else "")
        # Add the all_signals_count column
        display_df["all_signals_count"] = display_df["symbol"].map(symbol_signal_counts).apply(lambda x: int(x) if pd.notna(x) else 0)
    else:
        display_df["all_signals"] = ""  # Create empty column if data is missing
        display_df["all_signals_count"] = 0  # Create empty count column if data is missing

    return display_df


def calculate_performance_metrics(merged_df):
    """
    Calculate performance metrics including percentage changes and derived columns.

    Args:
        merged_df: DataFrame with signal data merged with market data

    Returns:
        DataFrame with added performance metrics columns
    """
    # Ensure numeric columns are properly converted
    merged_df["latest_price"] = pd.to_numeric(merged_df["latest_price"], errors="coerce")
    merged_df["signal_price"] = pd.to_numeric(merged_df["price"], errors="coerce")

    # Process market percentage change column if it exists
    if "market_pct_change" in merged_df.columns:
        merged_df["market_pct_change"] = (
            merged_df["market_pct_change"].astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
        )
        merged_df["market_pct_change"] = pd.to_numeric(merged_df["market_pct_change"], errors="coerce")
    else:
        merged_df["market_pct_change"] = pd.NA

    # Calculate percentage change between latest price and signal price
    merged_df["pct_change"] = ((merged_df["latest_price"] - merged_df["signal_price"]) / merged_df["signal_price"]) * 100

    # Round market_pct_change if it exists
    if "market_pct_change" in merged_df.columns:
        merged_df["market_pct_change"] = merged_df["market_pct_change"].round(2)

    # Round pct_change
    merged_df["pct_change"] = merged_df["pct_change"].round(2)

    # Format percentage change with arrows and circles
    def _fmt_pct(x):
        try:
            x = float(x)
        except Exception:
            return ""
        if pd.isna(x):
            return ""
        arrow = "▲" if x > 0 else ("▼" if x < 0 else "—")
        circle = "🟢" if x > 0 else ("🔴" if x < 0 else "⚪️")
        # Show the actual value with sign, not absolute value
        return f"{arrow} {x:+.2f}% {circle}"

    merged_df["Change vs signal(%)"] = merged_df["pct_change"].apply(_fmt_pct)

    return merged_df


def _get_latest_market_flight(symbols: list, exchange: str = "as", flight_url: str = "grpc://127.0.0.1:50001") -> pd.DataFrame:
    """
    通过 quant-lab Flight 服务拉取 K 线，取每只标的最近一根的 close 作为最新价。
    请求体与 flight_kline_client / quant-lab 一致。
    """
    import flight_kline_client as fkc

    if not symbols:
        return pd.DataFrame(columns=["code", "price", "change_percent"])

    tags = fkc.build_kline_tags(list(symbols), exchange, "1d")
    if not tags:
        return pd.DataFrame(columns=["code", "price", "change_percent"])

    end_ts = int(datetime.now().timestamp() * 1000)
    start_ts = int((datetime.now() - timedelta(days=5)).timestamp() * 1000)
    kline_df = fkc.fetch_kline_dataframe(tags, start_ts, end_ts, flight_url=flight_url)

    if kline_df is None or kline_df.empty:
        return pd.DataFrame(columns=["code", "price", "change_percent"])

    close_col = "close" if "close" in kline_df.columns else "Close"
    if close_col not in kline_df.columns:
        return pd.DataFrame(columns=["code", "price", "change_percent"])

    # 取每个 (exchange, symbol) 最新一根的 close
    ts_col = "end_ts" if "end_ts" in kline_df.columns else "timestamp"
    if ts_col not in kline_df.columns and "datetime" in kline_df.columns:
        kline_df = kline_df.sort_values("datetime", ascending=True)
        latest = kline_df.groupby(["exchange", "symbol"], as_index=False).last()
    else:
        if ts_col in kline_df.columns:
            kline_df = kline_df.sort_values(ts_col, ascending=True)
        latest = kline_df.groupby(["exchange", "symbol"], as_index=False).last()

    latest = latest.rename(columns={"symbol": "code", close_col: "price"})
    if "code" not in latest.columns and "symbol" in latest.columns:
        latest["code"] = latest["symbol"]
    latest["price"] = pd.to_numeric(latest["price"], errors="coerce")

    # 涨跌幅：若有前收，则 (price - prev_close) / prev_close * 100
    change_pct = []
    for _, row in latest.iterrows():
        ex, sym = row.get("exchange", exchange), row.get("code", row.get("symbol", ""))
        sub = kline_df[(kline_df["exchange"] == ex) & (kline_df["symbol"] == sym)]
        if ts_col in sub.columns:
            sub = sub.sort_values(ts_col)
        if len(sub) >= 2:
            prev = sub[close_col].iloc[-2]
            curr = sub[close_col].iloc[-1]
            change_pct.append(100.0 * (curr - prev) / prev if prev and prev != 0 else None)
        else:
            change_pct.append(None)
    latest["change_percent"] = change_pct

    return latest[["code", "price", "change_percent"]].copy()


def _normalize_market_df_columns(market_df):
    """东财/新浪等行情表 → 统一 code, price, change_percent。"""

    def _find_column(df, candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    code_col = _find_column(market_df, ["代码", "symbol", "code"])
    price_col = _find_column(market_df, ["最新价", "现价", "price", "trade", "now"])
    change_col = _find_column(
        market_df,
        ["涨跌幅", "涨跌额", "涨跌%", "pct_chg", "change_percent", "changepercent", "change"],
    )
    rename_map = {}
    if code_col:
        rename_map[code_col] = "code"
    if price_col:
        rename_map[price_col] = "price"
    if change_col:
        rename_map[change_col] = "change_percent"
    if rename_map:
        market_df = market_df.rename(columns=rename_map)
    return market_df


@st.cache_data(ttl=600, show_spinner=False)
def _get_latest_market_as_spot_full() -> pd.DataFrame:
    """
    A 股全市场现货（东财重试 → 新浪）。结果与请求方传入的 symbols 无关，
    便于 nested_bc / Performance 等页共用同一条缓存，避免重复打 akshare。
    """
    import time

    import akshare as ak

    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(2)
            market_df = ak.stock_zh_a_spot_em()
            if market_df is not None and not market_df.empty:
                return _normalize_market_df_columns(market_df)
        except Exception:
            if attempt < 2:
                continue
    try:
        time.sleep(1)
        market_df = ak.stock_zh_a_spot()
        if market_df is not None and not market_df.empty:
            st.info("东方财富不可用，已改用新浪数据源。")
            return _normalize_market_df_columns(market_df)
    except Exception:
        pass
    return pd.DataFrame()


@st.cache_data(ttl=600, show_spinner=False)
def _get_latest_market_as_flight_cached(symbols: tuple[str, ...]) -> pd.DataFrame:
    """A 股 Flight 按标的列表缓存（元组已排序，键稳定）。"""
    import os

    flight_url = os.environ.get("FLIGHT_URL", "grpc://127.0.0.1:50001")
    return _get_latest_market_flight(list(symbols), exchange="as", flight_url=flight_url)


def get_latest_market(source: str = "spot_em", symbols: list | None = None):
    """
    获取最新行情。source: "spot_em" | "spot" | "flight"。
    当 source=="flight" 时，从 quant-lab Flight 按 symbols 拉取 A 股最新价。

    缓存说明：东财/新浪全市场拉取与 symbols 无关，多页共享一条 TTL=600s 缓存；
    Flight 按排序后的 symbols 元组单独缓存。
    """
    sym_list = list(symbols) if symbols else []
    sym_t = tuple(sorted(sym_list))

    if source == "flight":
        with st.spinner("Fetching latest prices from Flight (quant-lab)..."):
            return _get_latest_market_as_flight_cached(sym_t)

    with st.spinner("Fetching latest market prices..."):
        df = _get_latest_market_as_spot_full()
    if df is not None and not df.empty:
        return df

    if sym_t:
        with st.spinner("Fetching latest prices from Flight (quant-lab)..."):
            fallback_df = _get_latest_market_as_flight_cached(sym_t)
        if not fallback_df.empty:
            st.info("东方财富/新浪均不可用，已自动改用 Flight 数据源。")
            return fallback_df

    st.error("获取 A 股行情失败，请稍后重试或切换为「最新价数据源 → Flight (quant-lab)」。")
    return pd.DataFrame()


def clear_a_share_latest_market_cache() -> None:
    """清空 A 股最新价缓存（东财/新浪全表 + Flight 按标的缓存）。供各页「刷新行情」调用。"""
    _get_latest_market_as_spot_full.clear()
    _get_latest_market_as_flight_cached.clear()


@st.cache_data(ttl=600, show_spinner=False)
def _get_latest_market_em():
    """EM 板块（概念+行业）最新价，统一返回 code, price, change_percent。"""
    import akshare as ak
    concept_df = ak.stock_board_concept_name_em()
    industry_df = ak.stock_board_industry_name_em()
    concept_df = concept_df.rename(columns={"板块代码": "code", "板块名称": "name", "最新价": "price", "涨跌幅": "change_percent"})
    industry_df = industry_df.rename(columns={"板块代码": "code", "板块名称": "name", "最新价": "price", "涨跌幅": "change_percent"})
    return pd.concat([concept_df, industry_df], ignore_index=True)[["code", "price", "change_percent"]].copy()


@st.cache_data(ttl=600, show_spinner=False)
def _get_latest_market_ths():
    """同花顺板块最新价，统一返回 code, price, change_percent。"""
    import akshare as ak
    board_df = ak.stock_board_industry_summary_ths()
    return board_df.rename(columns={"代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "change_percent"})[["code", "price", "change_percent"]].copy()


def get_latest_market_for_exchange(exchange: str, symbols: list | tuple | None = None, source_as: str = "spot_em") -> pd.DataFrame:
    """
    按 exchange 获取最新价，统一返回列：code, price, change_percent。
    供 Performance 等页复用。所有 exchange 均支持：主源失败时用 Flight (quant-lab) 兜底（需传入 symbols）。
    """
    symbols = list(symbols) if isinstance(symbols, tuple) else (symbols or [])
    if exchange == "as":
        return get_latest_market(source_as, symbols=tuple(symbols) if symbols else None)
    if exchange == "em":
        if source_as == "flight" and symbols:
            with st.spinner("Fetching latest prices from Flight (quant-lab)..."):
                return _get_latest_market_flight(symbols, exchange="em")
        with st.spinner("Fetching latest market prices..."):
            try:
                out = _get_latest_market_em()
                if out is not None and not out.empty:
                    return out
            except Exception:
                pass
            if symbols:
                st.info("东方财富板块不可用，已自动改用 Flight 数据源。")
                return _get_latest_market_flight(symbols, exchange="em")
        return pd.DataFrame(columns=["code", "price", "change_percent"])
    if exchange == "ths":
        if source_as == "flight" and symbols:
            with st.spinner("Fetching latest prices from Flight (quant-lab)..."):
                return _get_latest_market_flight(symbols, exchange="ths")
        with st.spinner("Fetching latest market prices..."):
            try:
                out = _get_latest_market_ths()
                if out is not None and not out.empty:
                    return out
            except Exception:
                pass
            if symbols:
                st.info("同花顺板块不可用，已自动改用 Flight 数据源。")
                return _get_latest_market_flight(symbols, exchange="ths")
        return pd.DataFrame(columns=["code", "price", "change_percent"])
    return pd.DataFrame(columns=["code", "price", "change_percent"])


def get_surge_symbols(
    symbols: list[str],
    *,
    exchange: str = "as",
    days: int = 5,
    threshold: float = 0.07,
    flight_url: str | None = None,
) -> set[str]:
    """返回最近 `days` 天内任意一天涨幅 >= `threshold` 的 symbol 集合。

    从 quant-lab Flight 拉取日线，按 (close - prev_close) / prev_close 计算日涨幅。
    若 Flight 不可用或数据不足则返回空集合。
    """
    import flight_kline_client as fkc

    if not symbols:
        return set()

    tags = fkc.build_kline_tags(list(symbols), exchange, "1d")
    if not tags:
        return set()

    end_ts = int(datetime.now().timestamp() * 1000)
    start_ts = int((datetime.now() - timedelta(days=int(days) + 2)).timestamp() * 1000)
    kline_df = fkc.fetch_kline_dataframe(
        tags, start_ts, end_ts, flight_url=flight_url or os.environ.get("FLIGHT_URL", "grpc://127.0.0.1:50001")
    )

    if kline_df is None or kline_df.empty:
        return set()

    close_col = "close" if "close" in kline_df.columns else "Close"
    if close_col not in kline_df.columns or "symbol" not in kline_df.columns:
        return set()

    ts_col = "end_ts" if "end_ts" in kline_df.columns else "timestamp"
    if ts_col not in kline_df.columns:
        return set()

    kline_df = kline_df.copy()
    kline_df[close_col] = pd.to_numeric(kline_df[close_col], errors="coerce")
    kline_df = kline_df.dropna(subset=[close_col])

    surge_symbols: set[str] = set()
    for symbol, group in kline_df.groupby("symbol", sort=False):
        group = group.sort_values(ts_col)
        closes = group[close_col].tolist()
        if len(closes) < 2:
            continue
        daily_returns = [
            (closes[i] - closes[i - 1]) / closes[i - 1]
            for i in range(1, len(closes))
            if closes[i - 1] and closes[i - 1] != 0
        ]
        if any(r >= threshold for r in daily_returns[-days:]):
            surge_symbols.add(str(symbol))

    return surge_symbols


def _calculate_macd_dif(close: pd.Series, fast: int = 12, slow: int = 26) -> pd.Series:
    """计算 MACD DIF 线：EMA(fast) - EMA(slow)。"""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    return ema_fast - ema_slow


def get_weekly_dif_positive_symbols(
    symbol_exchange_pairs: list[tuple[str, str]],
    *,
    flight_url: str | None = None,
) -> set[tuple[str, str]]:
    """返回周线 MACD DIF > 0 的 (symbol, exchange) 集合。

    从 quant-lab Flight 拉取周线，按 exchange 分组计算 MACD DIF，
    取最新一周 DIF > 0 的标的。仅处理 as / ths / asindex 三类 exchange。
    """
    import flight_kline_client as fkc

    if not symbol_exchange_pairs:
        return set()

    by_exchange: dict[str, list[str]] = {}
    for sym, ex in symbol_exchange_pairs:
        by_exchange.setdefault(ex, []).append(str(sym).strip())

    positive: set[tuple[str, str]] = set()
    default_url = flight_url or os.environ.get("FLIGHT_URL", "grpc://127.0.0.1:50001")
    end_ts = int(datetime.now().timestamp() * 1000)
    start_ts = int((datetime.now() - timedelta(days=365 * 3)).timestamp() * 1000)

    for ex, syms in by_exchange.items():
        if ex not in ("as", "ths", "asindex"):
            continue
        tags = fkc.build_kline_tags(syms, ex, "1w")
        if not tags:
            continue

        kline_df = fkc.fetch_kline_dataframe(tags, start_ts, end_ts, flight_url=default_url)
        if kline_df is None or kline_df.empty:
            continue

        close_col = "close" if "close" in kline_df.columns else "Close"
        if close_col not in kline_df.columns or "symbol" not in kline_df.columns:
            continue

        ts_col = "end_ts" if "end_ts" in kline_df.columns else "timestamp"
        if ts_col not in kline_df.columns:
            continue

        kline_df = kline_df.copy()
        kline_df[close_col] = pd.to_numeric(kline_df[close_col], errors="coerce")
        kline_df = kline_df.dropna(subset=[close_col])

        for symbol, group in kline_df.groupby("symbol", sort=False):
            group = group.sort_values(ts_col)
            closes = group[close_col].reset_index(drop=True)
            if len(closes) < 26:
                continue
            dif = _calculate_macd_dif(closes)
            if dif.iloc[-1] > 0:
                positive.add((str(symbol), ex))

    return positive


def _print_sql(query: str, params: tuple | list | None = None):
    """执行前打印 SQL（便于调试）。"""
    if params:
        print("[SQL]", query.strip(), "| params:", params)
    else:
        print("[SQL]", query.strip())


@st.cache_data(ttl=600, show_spinner="正在连接数据库（Neon 冷启动可能需要 1-2 分钟）...")
def load_data(time_window_days: int = 30, start_date: str | None = None, end_date: str | None = None,
              signal_name_prefix: str | None = None, signal_not: str | None = None):
    """Load signals from the database filtered by a time window.

    Args:
        time_window_days: look back N days from now (when start_date/end_date not set).
        start_date, end_date: explicit date range (takes precedence over time_window_days).
        signal_name_prefix: optional filter by signal_name LIKE '<prefix>%'.
        signal_not: optional filter to exclude rows where signal = '<value>' (e.g. 'SELL').
    """
    from utils import normalize_signal_date_field
    import psycopg

    conn_str = _get_conn_str()
    if not conn_str:
        st.error("未配置数据库连接。")
        return pd.DataFrame()

    try:
        with psycopg.connect(conn_str, connect_timeout=120) as conn:
            with conn.cursor() as cur:
                # 不查询 info 字段，该字段数据量太大会导致传输极慢
                columns = "id, pick_id, pick_dt, symbol_id, exchange, symbol, freq, symbol_name, signal_date, signal_name, signal, reason, price, score, shares, version, created_at, updated_at, reverse, side"
                clauses = []
                params: list = []
                if start_date and end_date:
                    clauses.append("signal_date >= %s")
                    clauses.append("signal_date < (%s::date + interval '1 day')")
                    params.extend([start_date, end_date])
                else:
                    ndays = int(time_window_days) if time_window_days is not None else 30
                    clauses.append(f"signal_date >= now() - interval '{ndays} days'")
                if signal_name_prefix:
                    clauses.append("signal_name LIKE %s")
                    params.append(signal_name_prefix + "%")
                if signal_not:
                    clauses.append("signal != %s")
                    params.append(signal_not)
                where = " AND ".join(clauses) if clauses else "TRUE"
                query = f"""
                SELECT {columns}
                FROM signal
                WHERE {where}
                ORDER BY signal_date DESC
                """
                _print_sql(query, tuple(params) if params else None)
                cur.execute(query, params or None)

                rows = cur.fetchall()
                colnames = [desc[0] for desc in cur.description]
                df = pd.DataFrame(rows, columns=colnames)
                df = normalize_signal_date_field(df, 'signal_date', 'Asia/Shanghai')
                
                # 处理 reverse 列：新增 display_symbol 列，如果 reverse 为 True 则显示为 "symbol:reverse"
                df['display_symbol'] = df.apply(
                    lambda row: f"{row['symbol']}:reverse" if row.get('reverse') else row['symbol'],
                    axis=1
                )
                
                return df
    except Exception as e:
        import sys
        st.error(f"Failed to load data from database: {e} (python: {sys.executable})")
        st.exception(e)
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_sector_constituents_from_db(sector_symbol: str, sector_exchange: str = 'em'):
    """Get constituent stocks for a given sector from the database.

    Args:
        sector_symbol: The sector symbol (e.g., 'BK0480')
        sector_exchange: The sector exchange (default: 'em')

    Returns:
        List of stock symbols that are constituents of the sector
    """
    sector_sql = """
        SELECT DISTINCT stock_symbol
        FROM sector_constituent
        WHERE sector_symbol = %s
          AND sector_exchange = %s
          AND snapshot_date = (
              SELECT MAX(snapshot_date)
              FROM sector_constituent
              WHERE sector_symbol = %s AND sector_exchange = %s
          )
    """
    params = (sector_symbol, sector_exchange, sector_symbol, sector_exchange)
    _print_sql(sector_sql, params)
    try:
        df = _query_df(sector_sql, params)
        return df["stock_symbol"].tolist() if not df.empty else []
    except Exception as e:
        st.warning(f"Failed to fetch constituents from database for {sector_symbol}: {e}")
        return []


# ============================================================================
# 共享数据库连接（复用，避免每个函数都新建连接）
# ============================================================================

def _get_conn_str():
    """获取 PostgreSQL 连接字符串。"""
    try:
        return st.secrets["connections"]["quantdb"]["url"]
    except (KeyError, FileNotFoundError, Exception):
        pass
    return os.environ.get("DATABASE_URL")


@st.cache_resource
def _get_db():
    """缓存的数据库连接（psycopg），供 data.py 内各函数复用。"""
    import psycopg
    conn_str = _get_conn_str()
    if not conn_str:
        st.error("未配置数据库连接。请检查 .streamlit/secrets.toml 或 DATABASE_URL 环境变量。")
        st.stop()
    return psycopg.connect(conn_str)


def _with_retry(operation):
    """包装数据库操作，在连接断开时自动重建并重试一次。"""
    import time
    import psycopg
    conn = _get_db()
    try:
        return operation(conn)
    except psycopg.Error:
        _get_db.clear()
        time.sleep(0.5)
        conn = _get_db()
        return operation(conn)


def _query_df(query: str, params=None) -> pd.DataFrame:
    """执行 SELECT，返回 DataFrame。"""
    def _do_query(conn):
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            return pd.DataFrame(rows, columns=cols)
    return _with_retry(_do_query)


def _execute(query: str, params=None) -> int:
    """执行 INSERT / UPDATE / DELETE，返回 affected rowcount。"""
    def _do_execute(conn):
        with conn.cursor() as cur:
            cur.execute(query, params)
            conn.commit()
            return cur.rowcount
    return _with_retry(_do_execute)


# ============================================================================
# 自选股分组管理
# ============================================================================
def get_instrument_groups() -> pd.DataFrame:
    """获取所有自选股分组。"""
    try:
        return _query_df("""
            SELECT g.name, g.description, g.created_at, g.updated_at,
                   COUNT(m.id) as member_count
            FROM instrument_group g
            LEFT JOIN instrument_group_member m ON g.name = m.group_name
            GROUP BY g.name, g.description, g.created_at, g.updated_at
            ORDER BY g.name
        """)
    except Exception as e:
        st.error(f"Failed to fetch instrument groups: {e}")
        return pd.DataFrame()


def create_instrument_group(name: str, description: str | None = None) -> bool:
    """创建自选股分组。"""
    try:
        return _execute(
            "INSERT INTO instrument_group (name, description) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
            (name, description)
        ) > 0
    except Exception as e:
        st.error(f"Failed to create instrument group: {e}")
        return False


def delete_instrument_group(name: str) -> bool:
    """删除自选股分组。"""
    try:
        return _execute("DELETE FROM instrument_group WHERE name = %s", (name,)) > 0
    except Exception as e:
        st.error(f"Failed to delete instrument group: {e}")
        return False


def get_instrument_group_members(group_name: str) -> pd.DataFrame:
    """获取指定分组的成员列表。"""
    try:
        return _query_df("""
            SELECT m.exchange, m.symbol, i.name as instrument_name, m.created_at
            FROM instrument_group_member m
            LEFT JOIN instrument i ON m.exchange = i.exchange AND m.symbol = i.symbol
            WHERE m.group_name = %s
            ORDER BY m.exchange, m.symbol
        """, (group_name,))
    except Exception as e:
        st.error(f"Failed to fetch group members: {e}")
        return pd.DataFrame()


def add_instrument_group_member(
    group_name: str,
    exchange: str,
    symbol: str,
    reverse: bool = False,
) -> bool:
    """向分组添加成员。"""
    try:
        return _execute(
            """INSERT INTO instrument_group_member (group_name, exchange, symbol, reverse)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (group_name, exchange, symbol)
               DO UPDATE SET reverse = EXCLUDED.reverse""",
            (group_name, exchange, symbol, reverse)
        ) > 0
    except Exception as e:
        st.error(f"Failed to add group member: {e}")
        return False


def remove_instrument_group_member(group_name: str, exchange: str, symbol: str) -> bool:
    """从分组移除成员。"""
    try:
        return _execute(
            "DELETE FROM instrument_group_member WHERE group_name = %s AND exchange = %s AND symbol = %s",
            (group_name, exchange, symbol)
        ) > 0
    except Exception as e:
        st.error(f"Failed to remove group member: {e}")
        return False


def get_kline_signals(
    exchange: str,
    symbol: str,
    start_date,
    end_date,
    freq: str | None = None,
) -> pd.DataFrame:
    """获取 K 线图上展示的多空信号（轻量，只取必要字段）。

    Parameters
    ----------
    freq : str | None
        若提供，只返回与当前图表周期一致的信号，避免在日线图上堆叠大量日内信号。
    """
    from utils import normalize_signal_date_field
    try:
        params: list = [exchange, symbol, start_date, end_date]
        freq_clause = ""
        if freq:
            params.append(freq)
            freq_clause = " AND freq = %s"
        df = _query_df(f"""
            SELECT signal_date, signal_name, side, signal, freq, price, reason, score
            FROM signal
            WHERE exchange = %s AND symbol = %s
              AND signal_date >= %s AND signal_date < (%s::date + interval '1 day')
              AND side IS NOT NULL{freq_clause}
            ORDER BY signal_date
        """, tuple(params))
        if not df.empty:
            df = normalize_signal_date_field(df, 'signal_date', 'Asia/Shanghai')
        return df
    except Exception as e:
        st.warning(f"查询 K 线信号失败: {e}")
        return pd.DataFrame()


def search_instruments(query: str, limit: int = 50) -> pd.DataFrame:
    """按代码、名称或别名搜索 instrument 表。"""
    try:
        return _query_df("""
            SELECT exchange, symbol, name, sub_exchange, alias
            FROM instrument
            WHERE symbol ILIKE %s
               OR name ILIKE %s
               OR EXISTS (
                   SELECT 1 FROM jsonb_array_elements_text(alias) AS a
                   WHERE a ILIKE %s
               )
            ORDER BY exchange, symbol
            LIMIT %s
        """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
    except Exception as e:
        st.error(f"Failed to search instruments: {e}")
        return pd.DataFrame()


def get_instruments_by_exchange(exchange: str) -> pd.DataFrame:
    """按交易所获取所有 instrument（含 alias，用于拼音搜索）。"""
    try:
        return _query_df("""
            SELECT exchange, symbol, name, sub_exchange, alias
            FROM instrument
            WHERE exchange = %s
            ORDER BY symbol
        """, (exchange,))
    except Exception as e:
        st.error(f"Failed to fetch instruments: {e}")
        return pd.DataFrame()


def get_exchanges() -> list[str]:
    """获取 instrument 表中所有不重复的交易所列表。"""
    try:
        df = _query_df("SELECT DISTINCT exchange FROM instrument ORDER BY exchange")
        return df["exchange"].tolist() if not df.empty else []
    except Exception as e:
        st.warning(f"Failed to fetch exchanges: {e}")
        return []


# ============================================================================
# 信号告警规则管理 (alert_rule)
# ============================================================================

def get_alert_rules() -> pd.DataFrame:
    """获取所有告警规则。"""
    try:
        return _query_df("""
            SELECT id, name, title, description, where_clause, enabled, feishu_group,
                   last_checked_id, created_at, updated_at
            FROM alert_rule
            ORDER BY id
        """)
    except Exception as e:
        st.error(f"获取告警规则失败: {e}")
        return pd.DataFrame()


def get_alert_rule(rule_id: int) -> dict | None:
    """获取单条告警规则。"""
    try:
        df = _query_df(
            "SELECT * FROM alert_rule WHERE id = %s", (rule_id,)
        )
        if not df.empty:
            return df.iloc[0].to_dict()
        return None
    except Exception as e:
        st.error(f"获取告警规则失败: {e}")
        return None


def create_alert_rule(
    name: str,
    where_clause: str,
    *,
    title: str = "",
    description: str = "",
    enabled: bool = True,
    feishu_group: str = "quant-alert",
) -> bool:
    """创建告警规则。"""
    try:
        return _execute("""
            INSERT INTO alert_rule (name, title, description, where_clause, enabled, feishu_group)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (name, title, description, where_clause, enabled, feishu_group)) > 0
    except Exception as e:
        st.error(f"创建告警规则失败: {e}")
        return False


def update_alert_rule(
    rule_id: int,
    *,
    name: str | None = None,
    title: str | None = None,
    description: str | None = None,
    where_clause: str | None = None,
    enabled: bool | None = None,
    feishu_group: str | None = None,
) -> bool:
    """更新告警规则。只更新提供的字段。"""
    fields = []
    params: list = []
    if name is not None:
        fields.append("name = %s")
        params.append(name)
    if title is not None:
        fields.append("title = %s")
        params.append(title)
    if description is not None:
        fields.append("description = %s")
        params.append(description)
    if where_clause is not None:
        fields.append("where_clause = %s")
        params.append(where_clause)
    if enabled is not None:
        fields.append("enabled = %s")
        params.append(enabled)
    if feishu_group is not None:
        fields.append("feishu_group = %s")
        params.append(feishu_group)
    if not fields:
        return False
    params.append(rule_id)
    try:
        return _execute(f"""
            UPDATE alert_rule
            SET {', '.join(fields)}, updated_at = NOW()
            WHERE id = %s
        """, params) > 0
    except Exception as e:
        st.error(f"更新告警规则失败: {e}")
        return False


def delete_alert_rule(rule_id: int) -> bool:
    """删除告警规则。"""
    try:
        return _execute("DELETE FROM alert_rule WHERE id = %s", (rule_id,)) > 0
    except Exception as e:
        st.error(f"删除告警规则失败: {e}")
        return False


def toggle_alert_rule(rule_id: int) -> bool:
    """切换告警规则的启用/禁用状态。"""
    try:
        return _execute("""
            UPDATE alert_rule
            SET enabled = NOT enabled, updated_at = NOW()
            WHERE id = %s
        """, (rule_id,)) > 0
    except Exception as e:
        st.error(f"切换告警规则状态失败: {e}")
        return False


def query_signals_by_rule(where_clause: str, limit: int = 50) -> pd.DataFrame:
    """根据告警规则的 WHERE 条件查询匹配的 signal。

    Args:
        where_clause: WHERE 条件（不含 WHERE 关键字）
        limit: 返回条数上限
    """
    from utils import normalize_signal_date_field

    try:
        # psycopg 会把 SQL 中的 % 当作占位符处理；where_clause 里若含 LIKE 'xxx%'
        # 这类字面量 %，需要提前转义为 %%，否则执行时报 "got '%'" 错误。
        safe_where = where_clause.replace("%", "%%")
        query = f"""
            SELECT id, pick_id, exchange, symbol, freq, symbol_name,
                   signal_date, signal_name, side, price, score, reason,
                   created_at
            FROM signal
            WHERE {safe_where}
            ORDER BY signal_date DESC
            LIMIT %s
        """
        df = _query_df(query, (limit,))
        if not df.empty:
            df = normalize_signal_date_field(df, 'signal_date', 'Asia/Shanghai')
        return df
    except Exception as e:
        st.error(f"查询匹配信号失败: {e}")
        return pd.DataFrame()