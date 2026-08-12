"""Backtest reports page (url_path=backtest_reports).

扫描 quant-lab/files/*.pkl，反序列化为 BacktestResult，渲染关键指标、
信号、Top/Bot 交易。点击"详情"展开完整报告。

数据契约（与 quant-lab/vbt/report.py 对齐）
------------------------------------------
- 文件名：``YYYYMMDD_HHMMSS_<pick_id>.pkl``
- 内容：``pickle.dump(framework.BacktestResult, ...)``
  - ``pf`` 字段已为 None（BacktestResult.__getstate__ 丢弃 vbt Portfolio）
  - 含 ``start / end / version / data / entries_map / exits_map / signals_map``
"""
from __future__ import annotations

import gc
import json
import os
import pickle
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# quant-lab 报告目录，可根据部署环境调整（与 vbt.report.DEFAULT_FILES_DIR 对齐）
QUANT_LAB_FILES = os.environ.get(
    "QUANT_LAB_FILES_DIR", "/home/lei/repo/quant-lab/files"
)

# 索引文件：缓存每个 pkl 的元信息，避免每次反序列化 4GB+ 大文件
_INDEX_BASENAME: str = ".signalview_report_index.json"
_INDEX_VERSION: int = 1

# 超过此大小的 pkl 在独立子进程中反序列化，避免主进程 OOM
_SUBPROCESS_SIZE_THRESHOLD_MB: int = 500


def _parse_filename_dt(filename: str) -> datetime | None:
    m = re.search(r"(\d{8})_(\d{6})", filename)
    if m:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y%m%d %H%M%S")
    return None


def _pick_id_from_filename(filename: str) -> str:
    """``YYYYMMDD_HHMMSS_<pick_id>.pkl`` → ``<pick_id>``。"""
    base = os.path.splitext(filename)[0]
    parts = base.split("_", 2)
    return parts[2] if len(parts) >= 3 else base


def _safe_load_pickle(path: str) -> dict[str, Any] | None:
    """加载 pkl 为 dict 视图（即使 dataclass 缺失字段也不崩）。"""
    try:
        with open(path, "rb") as f:
            obj = pickle.load(f)
    except Exception:
        return None
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    if isinstance(obj, dict):
        return obj
    return {"_raw": obj}


def _freq_str(result: dict[str, Any]) -> str:
    """汇总 data 字典里的 freq。"""
    freqs: set[str] = set()
    for key in (result.get("data") or {}):
        parts = str(key).split(":")
        if len(parts) >= 3:
            freqs.add(parts[2])
    return ",".join(sorted(freqs)) or "-"


def _stats_daily(result: dict[str, Any]) -> pd.Series:
    """优先读取 pkl 中预存的 stats_daily；缺失时再 fallback 到 raw 对象方法。"""
    cached = result.get("stats_daily")
    if isinstance(cached, dict) and cached:
        try:
            return pd.Series(cached)
        except Exception:
            pass
    obj = result.get("_raw")
    if obj is not None and hasattr(obj, "stats_daily"):
        try:
            return obj.stats_daily()
        except Exception:
            pass
    return pd.Series(dtype=float)


def _signals_df(result: dict[str, Any]) -> pd.DataFrame:
    """从 signals_map 展平为 DataFrame。"""
    smap = result.get("signals_map") or {}
    rows = []
    for key, sigs in smap.items():
        for s in sigs:
            rows.append(
                {
                    "symbol_id": key,
                    "signal_date": s.get("date"),
                    "price": s.get("price"),
                    "signal_name": s.get("signal_name", ""),
                }
            )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["signal_date"] = pd.to_datetime(df["signal_date"], errors="coerce")
    return df


def _n_trades(result: dict[str, Any]) -> int:
    pf = result.get("pf")
    if pf is not None and hasattr(pf, "trades"):
        try:
            return len(pf.trades.records_readable)
        except Exception:
            return 0
    return 0


def _summary_row(filename: str, pkl_path: str) -> dict[str, Any] | None:
    """从 pkl 提取列表展示所需的元信息。失败返回 None。"""
    result = _safe_load_pickle(pkl_path)
    if result is None:
        return None
    stats = _stats_daily(result)
    sigs = _signals_df(result)
    def _f(k):
        return float(stats[k]) if k in stats and pd.notna(stats[k]) else None
    return {
        "filename": filename,
        "base": os.path.splitext(filename)[0],
        "pick_id": _pick_id_from_filename(filename),
        "created_at": _parse_filename_dt(filename),
        "start": result.get("start"),
        "end": result.get("end"),
        "version": result.get("version"),
        "freqs": _freq_str(result),
        "n_signals": len(sigs),
        "n_trades": _n_trades(result),
        "total_return": _f("Total Return [%]"),
        "annual_return": _f("Annualized Return [%]"),
        "sharpe": _f("Sharpe Ratio"),
        "max_dd": _f("Max Drawdown [%]"),
        "pkl_path": pkl_path,
    }


# 子进程加载脚本：大文件在独立 Python 进程中反序列化，避免主进程 OOM
_SIGNALVIEW_ROOT = str(Path(__file__).resolve().parents[1])

_SUBPROCESS_LOAD_SCRIPT = """
import json, sys
sys.path.insert(0, {root!r})
from app_pages.backtest_reports import _summary_row
filename = sys.argv[1]
pkl_path = sys.argv[2]
row = _summary_row(filename, pkl_path)
print(json.dumps(row, default=lambda o: o.isoformat() if hasattr(o, \"isoformat\") else str(o)))
"""


def _summary_row_in_subprocess(filename: str, pkl_path: str) -> dict[str, Any] | None:
    """在独立子进程中加载大 pkl 并提取元信息。

    子进程退出后其占用的内存会被操作系统回收，适合 500MB+ 的大文件，
    避免主进程同时驻留多个反序列化后的巨大对象。
    """
    script = _SUBPROCESS_LOAD_SCRIPT.format(root=_SIGNALVIEW_ROOT)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, filename, pkl_path],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if proc.returncode != 0:
            return None
        row = json.loads(proc.stdout)
        if row is None:
            return None
        if row.get("created_at"):
            row["created_at"] = datetime.fromisoformat(row["created_at"])
        return row
    except Exception:
        return None


# ---------- 索引：避免每次反序列化大 pkl ----------

def _index_path() -> str:
    return os.path.join(QUANT_LAB_FILES, _INDEX_BASENAME)


def _json_default(obj: Any) -> Any:
    """datetime 等对象在写入 JSON 索引前的序列化钩子。"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_object_hook(d: dict[str, Any]) -> dict[str, Any]:
    """读取 JSON 索引时，把 ISO 格式时间戳还原为 datetime。"""
    if "created_at" in d and isinstance(d["created_at"], str):
        try:
            d["created_at"] = datetime.fromisoformat(d["created_at"])
        except ValueError:
            pass
    return d


def _load_index() -> dict[str, Any]:
    """读取索引文件；不存在或版本不符时返回空索引。"""
    path = _index_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            idx = json.load(f, object_hook=_json_object_hook)
    except Exception:
        return {"version": _INDEX_VERSION, "entries": {}}
    if idx.get("version") != _INDEX_VERSION:
        return {"version": _INDEX_VERSION, "entries": {}}
    return idx


def _save_index(idx: dict[str, Any]) -> None:
    """原子写索引文件。"""
    path = _index_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(idx, f, ensure_ascii=False, default=_json_default)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _file_identity(path: str) -> tuple[float, int] | None:
    """返回文件 (mtime, size)，用于判断 pkl 是否被替换。"""
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except OSError:
        return None


def _build_index_incrementally(pkl_names: tuple[str, ...]) -> list[dict[str, Any]]:
    """基于现有索引增量更新，返回当前所有有效 pkl 的 summary rows。

    只加载新增或 mtime/size 变化的文件；已索引且未变化的文件直接复用缓存行。
    """
    idx = _load_index()
    entries: dict[str, Any] = idx.get("entries", {})
    current_names = set(pkl_names)

    # 清理已删除的文件条目
    for fname in list(entries.keys()):
        if fname not in current_names:
            del entries[fname]

    rows: list[dict[str, Any]] = []
    for fname in pkl_names:
        pkl_path = os.path.join(QUANT_LAB_FILES, fname)
        identity = _file_identity(pkl_path)
        if identity is None:
            entries.pop(fname, None)
            continue

        mtime, size = identity
        cached = entries.get(fname)
        if cached and cached.get("mtime") == mtime and cached.get("size") == size:
            row = cached.get("row")
        else:
            # 大文件在子进程中加载，避免主进程 OOM
            if size > _SUBPROCESS_SIZE_THRESHOLD_MB * 1024 * 1024:
                row = _summary_row_in_subprocess(fname, pkl_path)
            else:
                row = _summary_row(fname, pkl_path)
            if row is not None:
                entries[fname] = {
                    "mtime": mtime,
                    "size": size,
                    "row": row,
                }
            else:
                entries.pop(fname, None)
                continue

        if row is not None:
            rows.append(row)

        # 大 pkl 反序列化后及时回收内存，避免多个 4GB+ 文件同时驻留
        gc.collect()

    _save_index(idx)
    return rows


def _scan_cache_key() -> tuple[tuple[str, float, int], ...]:
    """计算扫描缓存键：每个 pkl 的 (name, mtime, size) 元组。

    比目录 mtime 更精确：新增 / 删除 / 替换 / 修改任一 pkl 都会改变 key，
    触发 st.cache_data 失效；同时避免目录 mtime 在极短时间内未更新的问题。
    """
    if not os.path.isdir(QUANT_LAB_FILES):
        return ()
    entries: list[tuple[str, float, int]] = []
    for fname in sorted(os.listdir(QUANT_LAB_FILES)):
        if not fname.endswith(".pkl"):
            continue
        pkl_path = os.path.join(QUANT_LAB_FILES, fname)
        try:
            st = os.stat(pkl_path)
            entries.append((fname, st.st_mtime, st.st_size))
        except OSError:
            entries.append((fname, 0.0, 0))
    return tuple(entries)


@st.cache_data(ttl=30, show_spinner=False)
def _list_reports_cached(key: tuple[tuple[str, float, int], ...]) -> pd.DataFrame:
    """list_reports 的缓存实现。参数 hash 变化时缓存失效。"""
    pkl_names = tuple(entry[0] for entry in key)
    rows = _build_index_incrementally(pkl_names)
    df = pd.DataFrame(rows)
    if not df.empty and "created_at" in df.columns:
        df = df.sort_values("created_at", ascending=False)
    return df


def list_reports(force_rebuild: bool = False) -> pd.DataFrame:
    """扫描 quant-lab/files/*.pkl，返回列表 DataFrame（30s 缓存 + mtime 失效）。

    缓存策略：30s TTL + 入参为 (dir_mtime, sorted(pkl_names))。新增 / 删除 /
    替换 pkl 文件会改变入参 hash，缓存自动失效。30s TTL 兜底防止目录外
    文件被替换但 mtime 不变的场景。

    性能：通过 ``.signalview_report_index.json`` 缓存每个 pkl 的元信息，
    避免每次反序列化大文件。当 pkl mtime/size 不变时直接复用索引。
    """
    if force_rebuild:
        _save_index({"version": _INDEX_VERSION, "entries": {}})
        _list_reports_cached.clear()
    return _list_reports_cached(_scan_cache_key())


def delete_report(base: str) -> list[str]:
    """删除指定 base 的 pkl 文件，返回实际删除的文件名列表。"""
    deleted = []
    path = os.path.join(QUANT_LAB_FILES, f"{base}.pkl")
    if os.path.exists(path):
        try:
            os.remove(path)
            deleted.append(os.path.basename(path))
        except OSError:
            pass
    return deleted


def _diagnose_pkl(result: dict[str, Any] | None) -> str:
    """诊断 pkl 内容状态：完整 / 无信号 / 无数据 / 损坏。

    Returns:
        ``"ok" | "empty_data" | "no_signals" | "no_pf" | "corrupt"``

    注意：pkl 中 pf 字段始终为 None（``BacktestResult.__getstate__`` 丢弃），但
    stats_daily 字段被 vbt.report.save_pickle 预存。所以"ok"判断看 stats_daily
    是否非空，而非 pf 是否存在。
    """
    if result is None:
        return "corrupt"
    data = result.get("data") or {}
    signals_map = result.get("signals_map") or {}
    n_signals = sum(len(v) for v in signals_map.values())
    if not data:
        return "empty_data"
    if n_signals == 0:
        return "no_signals"
    # pf 在 pkl 中始终为 None（设计如此）；有 stats_daily 就算"完整"
    stats = result.get("stats_daily") or {}
    if not stats:
        return "no_pf"
    return "ok"


def _render_detail(base: str) -> None:
    """展开单次回测的完整报告。"""
    pkl_path = os.path.join(QUANT_LAB_FILES, f"{base}.pkl")
    result = _safe_load_pickle(pkl_path)
    if result is None:
        st.error(f"无法加载 pkl：{pkl_path}")
        return

    diagnosis = _diagnose_pkl(result)
    if diagnosis == "empty_data":
        st.error(
            f"此 pkl 不含回测数据（data 字段为空）。"
            f"可能是 vbt 回测未拉取到任何标的，或 pkl 损坏。"
            f"路径：{pkl_path}"
        )
        return
    if diagnosis == "corrupt":
        st.error(f"无法加载 pkl：{pkl_path}")
        return

    st.subheader(f"📈 {base}")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("回测区间", f"{result.get('start')} ~ {result.get('end')}")
    c2.metric("周期", _freq_str(result))
    c3.metric("策略版本", str(result.get("version")))
    c4.metric("标的数", len(result.get("data") or {}))

    if diagnosis == "no_signals":
        st.warning(
            "此回测在指定区间内未触发任何信号（signals_map 为空）。"
            "可能原因：区间太短 / 策略条件过严 / 数据缺失。"
        )
    elif diagnosis == "no_pf":
        st.warning(
            "此 pkl 不含 vectorbt Portfolio（pf=None），可能由旧版工具生成或"
            "pf 构造异常。指标数据不可用，仅展示信号与元信息。"
        )

    st.divider()
    stats = _stats_daily(result)
    if not stats.empty:
        st.markdown("**关键指标（按日重采样口径）**")
        st.dataframe(stats.to_frame("数值"), width="stretch")
    else:
        st.info("无组合级指标（pf 为 None 或 stats_daily 不可用）。")

    sigs = _signals_df(result)
    st.markdown(f"**信号明细（{len(sigs)} 条）**")
    if not sigs.empty:
        st.dataframe(sigs, width="stretch", height=300)
    else:
        st.caption("（无信号）")


def page_backtest_reports() -> None:
    st.set_page_config(page_title="Backtest Reports", layout="wide")
    st.title("📊 回测报告管理")
    st.caption(f"自动发现自 `{QUANT_LAB_FILES}`（pkl-only，反序列化渲染）")

    if not os.path.isdir(QUANT_LAB_FILES):
        st.error(f"报告目录不存在：{QUANT_LAB_FILES}")
        st.stop()

    if st.button("🔄 刷新列表", width="content"):
        st.rerun()

    force_rebuild = st.button("🔄 重建索引", width="content", help="当索引损坏或需要强制重新扫描所有 pkl 时使用。大文件较多时可能需要一些时间。")

    df = list_reports(force_rebuild=force_rebuild)
    if df.empty:
        st.info("暂无报告。在 quant-lab 中运行回测后会自动出现在这里。")
        st.stop()

    filter_text = st.text_input(
        "筛选报告", placeholder="pick_id / 日期 / 周期"
    ).strip().lower()
    if filter_text:
        mask = df.astype(str).apply(
            lambda row: row.str.lower().str.contains(filter_text, na=False).any(),
            axis=1,
        )
        df = df[mask]

    if df.empty:
        st.info("没有匹配筛选条件的报告。")
        st.stop()

    st.subheader(f"共 {len(df)} 份报告")

    _display_df = df[
        [
            "filename",
            "pick_id",
            "created_at",
            "freqs",
            "n_signals",
            "n_trades",
            "total_return",
            "sharpe",
            "max_dd",
        ]
    ].copy()
    _display_df["created_at"] = pd.to_datetime(_display_df["created_at"]).dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    for col in ("total_return", "max_dd"):
        _display_df[col] = _display_df[col].apply(
            lambda v: f"{v:.2f}%" if pd.notna(v) else "-"
        )
    _display_df["sharpe"] = _display_df["sharpe"].apply(
        lambda v: f"{v:.4f}" if pd.notna(v) else "-"
    )
    _display_df.rename(
        columns={
            "filename": "文件名",
            "pick_id": "策略",
            "created_at": "生成时间",
            "freqs": "周期",
            "n_signals": "信号数",
            "n_trades": "交易数",
            "total_return": "总收益",
            "sharpe": "Sharpe",
            "max_dd": "最大回撤",
        },
        inplace=True,
    )
    st.dataframe(_display_df, width="stretch", hide_index=True)

    st.divider()
    # 每份报告一个独立 item：左侧元信息 + 右侧"📑 详情"按钮，按钮在 item 内部。
    # 点击跳转 url_path=backtest_report_detail（独立详情页，列表页不渲染详情）。
    for _, row in df.iterrows():
        with st.container(border=True):
            c_info, c_act = st.columns([7, 1])
            with c_info:
                st.markdown(
                    f"**{row['base']}**  &nbsp; "
                    f"<span style='color:gray'>({row['pick_id']})</span>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    pd.to_datetime(row["created_at"]).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            with c_act:
                st.link_button(
                    "📑 详情",
                    url=f"/backtest_report_detail?base={row['base']}",
                    width="stretch",
                )

    st.divider()
    st.subheader("🗑️ 删除报告")
    to_delete = st.multiselect(
        "选择要删除的报告",
        options=df["filename"].tolist(),
        format_func=lambda x: f"{x}  ({df[df['filename'] == x]['pick_id'].iloc[0]})",
    )
    if to_delete and st.button(
        f"🗑️ 删除选中的 {len(to_delete)} 份报告", type="primary"
    ):
        deleted_all = []
        for fname in to_delete:
            deleted = delete_report(os.path.splitext(fname)[0])
            deleted_all.extend(deleted)
        st.success(f"已删除 {len(deleted_all)} 个文件：{', '.join(deleted_all)}")
        st.rerun()
