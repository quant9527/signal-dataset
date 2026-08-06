"""signalview/app_pages/backtest_reports 单元测试。

不连 streamlit / 网络 / 数据库；用 tmp_path 构造伪 pkl，验证：
- 文件名解析（pick_id / 时间戳）
- pkl 安全加载（坏文件不崩）
- 列表汇总（list_reports）
- 删除（仅删 pkl）
"""
from __future__ import annotations

import pickle
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

# signalview 根目录加到 path（与现有 tests 一致）
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app_pages import backtest_reports as br  # noqa: E402


@pytest.fixture
def fake_files_dir(monkeypatch, tmp_path):
    """把 QUANT_LAB_FILES 重定向到 tmp_path，不污染真实目录。"""
    monkeypatch.setattr(br, "QUANT_LAB_FILES", str(tmp_path))
    # 每次 fixture 触发清掉 st.cache_data 缓存（测试间不共享旧目录结果）
    br._list_reports_cached.clear()
    return tmp_path


def _make_dummy_pkl(path: Path, *, start="2026-01-01", end="2026-07-01",
                    n_signals: int = 0) -> None:
    """构造一个最小 BacktestResult.__getstate__ 风格的 pkl。"""
    idx = pd.date_range("2026-01-01", periods=3, freq="1D")
    state = {
        "pf": None,
        "data": {"as:000001:1d": pd.DataFrame({"close": [10, 11, 12]}, index=idx)},
        "entries_map": {"as:000001:1d": [False, True, False]},
        "exits_map": {"as:000001:1d": [False, False, True]},
        "signals_map": {
            "as:000001:1d": [
                {"date": idx[1], "price": 11.0, "signal_name": "demo"}
            ]
            if n_signals
            else []
        },
        "start": start,
        "end": end,
        "version": 5,
    }
    with open(path, "wb") as f:
        pickle.dump(state, f)


def test_pick_id_from_filename():
    assert br._pick_id_from_filename("20260805_213928_cl2b_pair.pkl") == "cl2b_pair"
    assert br._pick_id_from_filename("weird.pkl") == "weird"
    # 仅一个下划线：base 含时间戳，pick_id 为空字符串兜底
    assert br._pick_id_from_filename("single.pkl") == "single"


def test_parse_filename_dt():
    dt = br._parse_filename_dt("20260805_213928_cl2b_pair.pkl")
    assert dt == datetime(2026, 8, 5, 21, 39, 28)
    assert br._parse_filename_dt("garbage.pkl") is None


def test_safe_load_pickle_returns_dict(fake_files_dir):
    pkl = fake_files_dir / "x.pkl"
    _make_dummy_pkl(pkl)
    d = br._safe_load_pickle(str(pkl))
    assert isinstance(d, dict)
    assert d["start"] == "2026-01-01"
    assert d["version"] == 5


def test_safe_load_pickle_handles_garbage(fake_files_dir):
    bad = fake_files_dir / "bad.pkl"
    bad.write_bytes(b"not a pickle at all")
    assert br._safe_load_pickle(str(bad)) is None


def test_safe_load_pickle_missing_file():
    assert br._safe_load_pickle("/tmp/nonexistent_xyz.pkl") is None


def test_list_reports_empty(fake_files_dir):
    assert br.list_reports().empty


def test_list_reports_summary(fake_files_dir):
    _make_dummy_pkl(fake_files_dir / "20260805_100000_alpha.pkl", n_signals=1)
    _make_dummy_pkl(fake_files_dir / "20260804_100000_beta.pkl")
    df = br.list_reports()
    assert len(df) == 2
    assert set(df["pick_id"]) == {"alpha", "beta"}
    # 时间倒序
    assert df.iloc[0]["pick_id"] == "alpha"
    assert df.iloc[1]["pick_id"] == "beta"
    # 必含字段
    for col in ("filename", "pick_id", "created_at", "start", "end",
                "freqs", "n_signals", "n_trades"):
        assert col in df.columns


def test_list_reports_skips_garbage(fake_files_dir):
    _make_dummy_pkl(fake_files_dir / "20260805_100000_good.pkl")
    (fake_files_dir / "20260805_100000_bad.pkl").write_bytes(b"garbage")
    (fake_files_dir / "README.md").write_text("# ignore")
    df = br.list_reports()
    assert len(df) == 1
    assert df.iloc[0]["pick_id"] == "good"


def test_list_reports_skips_non_pkl(fake_files_dir):
    """只接受 .pkl，html 文件被忽略。"""
    _make_dummy_pkl(fake_files_dir / "20260805_100000_x.pkl")
    (fake_files_dir / "20260805_100000_y.html").write_text("<html></html>")
    df = br.list_reports()
    assert len(df) == 1
    assert df.iloc[0]["pick_id"] == "x"


def test_delete_report_only_pkl(fake_files_dir):
    _make_dummy_pkl(fake_files_dir / "20260805_100000_x.pkl")
    deleted = br.delete_report("20260805_100000_x")
    assert deleted == ["20260805_100000_x.pkl"]
    assert not (fake_files_dir / "20260805_100000_x.pkl").exists()


def test_delete_report_idempotent(fake_files_dir):
    """重复删除不抛错。"""
    deleted = br.delete_report("never_existed")
    assert deleted == []


def test_freq_str_extraction(fake_files_dir):
    pkl = fake_files_dir / "20260805_100000_multi.pkl"
    idx = pd.date_range("2026-01-01", periods=2, freq="1D")
    state = {
        "pf": None,
        "data": {
            "as:000001:1h": pd.DataFrame({"close": [1]}, index=idx),
            "as:000002:1d": pd.DataFrame({"close": [2]}, index=idx),
        },
        "entries_map": {},
        "exits_map": {},
        "signals_map": {},
        "start": "2026-01-01",
        "end": "2026-07-01",
        "version": 5,
    }
    with open(pkl, "wb") as f:
        pickle.dump(state, f)
    df = br.list_reports()
    assert df.iloc[0]["freqs"] == "1d,1h"


# ---------- 诊断（_diagnose_pkl） ----------

class TestDiagnosePkl:
    def test_corrupt_when_none(self):
        assert br._diagnose_pkl(None) == "corrupt"

    def test_empty_data(self):
        assert br._diagnose_pkl({"data": {}, "signals_map": {}}) == "empty_data"

    def test_no_signals(self):
        state = {
            "data": {"as:000001:1d": pd.DataFrame({"close": [1]})},
            "signals_map": {},
            "pf": None,
        }
        assert br._diagnose_pkl(state) == "no_signals"

    def test_no_pf_when_signals_present(self):
        idx = pd.date_range("2026-01-01", periods=1, freq="1D")
        state = {
            "data": {"as:000001:1d": pd.DataFrame({"close": [1]}, index=idx)},
            "signals_map": {
                "as:000001:1d": [{"date": idx[0], "price": 1.0, "signal_name": "x"}]
            },
            "pf": None,
        }
        assert br._diagnose_pkl(state) == "no_pf"

    def test_ok_with_stats_daily(self):
        idx = pd.date_range("2026-01-01", periods=1, freq="1D")
        state = {
            "data": {"as:000001:1d": pd.DataFrame({"close": [1]}, index=idx)},
            "signals_map": {
                "as:000001:1d": [{"date": idx[0], "price": 1.0, "signal_name": "x"}]
            },
            "pf": None,
            "stats_daily": {"Total Return [%]": 1.0, "Sharpe Ratio": 0.5},
        }
        assert br._diagnose_pkl(state) == "ok"


# ---------- AppTest 回归 ----------

class TestPageRenders:
    """防止 streamlit API 升级或 page_backtest_reports 重构破坏 UI。"""

    def test_page_renders_without_exception(self, fake_files_dir):
        from streamlit.testing.v1 import AppTest

        # 至少放一个 pkl 让列表非空，触发 selectbox / subheader
        _make_dummy_pkl(fake_files_dir / "20260805_100000_alpha.pkl")

        runner = (
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "import streamlit as st\n"
            "from app_pages.backtest_reports import page_backtest_reports\n"
            "page_backtest_reports()\n"
        )
        at = AppTest.from_string(runner)
        at.run()

        # 关键元素都在
        assert list(at.exception) == [], f"page 抛异常: {list(at.exception)}"
        titles = [t.value for t in at.title]
        assert "📊 回测报告管理" in titles
        subs = [s.value for s in at.subheader]
        assert any("共 1 份报告" in s for s in subs), f"subheaders: {subs}"
        # selectbox 列出 alpha
        for sb in at.selectbox:
            if sb.label == "选择一份报告查看详情":
                assert any("alpha" in opt for opt in sb.options)
