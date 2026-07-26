"""Shared helpers for the K-line fullscreen page.

Internal module — do not register with st.navigation.

Exports query-params primitives used by the fullscreen K-line page
(`app_pages.kline_fullscreen`).
"""
from __future__ import annotations

from datetime import date


def _qp_value(key: str) -> str:
    """Read a query-param value, trimmed; empty string if absent.

    Streamlit testing may expose a single value as a list; take the first item.
    """
    from streamlit import query_params
    value = query_params.get(key, "") or ""
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value).strip()


def qp_str(key: str) -> str:
    """Read a query-param string, trimmed; empty string if absent."""
    return _qp_value(key)


def qp_bool(key: str) -> bool:
    """Read a query-param boolean: 1/true/yes are truthy."""
    return _qp_value(key) in ("1", "true", "yes")


def parse_iso_date(s: str) -> date | None:
    """Parse YYYY-MM-DD (or any ISO prefix); None on empty/garbage."""
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None