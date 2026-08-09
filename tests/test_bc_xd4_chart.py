"""BC XD4 页面端到端冒烟：拖动 slider 到 60 天窗口最早日期，曲线图数据应覆盖整个窗口。

通过 monkey patch 拦截 `st.line_chart` 抓取最后一次入参 DataFrame。
此测试依赖本地真实 signal 数据，仅作开发期冒烟用。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from streamlit.testing.v1 import AppTest


RUNNER_TEMPLATE = r'''
import streamlit as st
from app_pages.signal_bc_xd4 import page_signal_bc_xd4

page_signal_bc_xd4()
'''


def test_chart_covers_60d_window_after_slider_change(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}

    real_line_chart = __import__("streamlit").line_chart

    def _spy(df, *args, **kwargs):
        captured["df"] = df.copy()
        return real_line_chart(df, *args, **kwargs)

    import streamlit as st_module

    # 在 import 之前先把 spy 装到 streamlit 上
    monkeypatch.setattr(st_module, "line_chart", _spy)

    runner = tmp_path / "bc_xd4_runner.py"
    runner.write_text(RUNNER_TEMPLATE)
    at = AppTest.from_file(str(runner), default_timeout=30)
    at.run()

    sliders = at.slider
    if not sliders:
        raise AssertionError("页面没有渲染任何 slider，无法验证日期范围。")
    slider = sliders[0]
    today = date.today()
    expected_min = today - timedelta(days=60)
    print("slider min/max:", slider.min, "/", slider.max)
    print("expected window:", expected_min, "->", today)

    slider.set_value((expected_min, today))
    at.run()

    if "df" not in captured:
        raise AssertionError("未拦截到 st.line_chart 调用")
    df = captured["df"]
    print("chart df columns:", list(df.columns))
    print("chart df index min/max:", df.index.min(), "/", df.index.max())
    min_date = date.fromisoformat(str(df.index.min()))
    max_date = date.fromisoformat(str(df.index.max()))
    assert min_date <= expected_min, (
        f"曲线图最早日期 {min_date} 应不晚于 60 天前 {expected_min}"
    )
    assert max_date >= today, (
        f"曲线图最晚日期 {max_date} 应不早于今天 {today}"
    )
