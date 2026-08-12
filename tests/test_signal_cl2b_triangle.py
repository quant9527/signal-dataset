"""signal_cl2b_triangle 页面单元测试。

不连数据库 / Streamlit UI；仅验证常量、模块入口与纯函数逻辑。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_pages.signal_cl2b_triangle import _filter_by_date_range  # noqa: E402
from signal_constants import CL2B_TRIANGLE_PREFIX  # noqa: E402


def test_cl2b_triangle_prefix_constant():
    """CL2B_TRIANGLE_PREFIX 应指向 cl2b_triangle 系列信号。"""
    assert CL2B_TRIANGLE_PREFIX == "cl2b_triangle"


def test_filter_by_date_range_filters_signal_dates():
    """_filter_by_date_range 应仅保留指定日期范围内的记录。"""
    df = pd.DataFrame(
        {
            "symbol": ["000001", "000002", "000003"],
            "signal_date": pd.to_datetime(
                ["2026-08-01", "2026-08-05", "2026-08-10"]
            ),
        }
    )
    result = _filter_by_date_range(df, date(2026, 8, 2), date(2026, 8, 9))

    assert len(result) == 1
    assert result["symbol"].iloc[0] == "000002"


def test_filter_by_date_range_empty_df():
    """空 DataFrame 应直接返回空。"""
    df = pd.DataFrame(columns=["symbol", "signal_date"])
    result = _filter_by_date_range(df, date(2026, 8, 1), date(2026, 8, 10))
    assert result.empty


def test_filter_by_date_range_missing_column():
    """缺少 signal_date 列时应原样返回。"""
    df = pd.DataFrame({"symbol": ["000001"]})
    result = _filter_by_date_range(df, date(2026, 8, 1), date(2026, 8, 10))
    pd.testing.assert_frame_equal(result, df)
