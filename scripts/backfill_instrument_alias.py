"""一次性 backfill instrument 表的 alias 列：用 heteronym 多音字算法重算。

背景：
- atlas 端 ConvertFromFlinkProfile 之前用 LazyPinyin 只取每个汉字的单一读音首字母，
  导致多音字公司名（如"长盈通"读 cháng 或 zhǎng）只存了 zyt 一种拼写，
  selectbox 搜 cyt 时找不到。
- 新版用 SinglePinyin(heteronym=true) + 笛卡尔积展开所有可能读音组合。
- 本脚本用 Python pypinyin 实现同样的逻辑，UPDATE 已有 instrument 表的 alias 列，
  让存量数据也获得多音字 alias。

执行：
    ./.venv/bin/python scripts/backfill_instrument_alias.py [--dry-run]

约束：
- alias 数组去重后写入，空字符串跳过
- 已含正确多音字 alias 的行不动（幂等）
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any

sys.path.insert(0, "/home/lei/repo/signalview")

import psycopg.types.json
import pypinyin
from pypinyin import Style

import data


def _chinese_chars(s: str) -> list[str]:
    """提取字符串中的中文字符。"""
    return re.findall(r"[\u4e00-\u9fff]", s)


def _initial_groups(s: str) -> list[list[str]]:
    """对每个中文字符返回「所有可能拼音首字母」集合（heteronym 模式）。

    Args:
        s: 任意字符串。

    Returns:
        每个中文字符对应一个首字母集合（去重）。
        例："长盈通" → [[z, c], [y], [t]]

    举例验证：
        >>> _initial_groups("长盈通")
        [['z', 'c'], ['y'], ['t']]
    """
    chars = _chinese_chars(s)
    if not chars:
        return []
    # heteronym=True 让单字返回所有可能拼音
    pys = pypinyin.pinyin(chars, style=Style.NORMAL, heteronym=True)
    groups: list[list[str]] = []
    for char_pys in pys:
        seen: set[str] = set()
        first_letters: list[str] = []
        for py in char_pys:
            if not py:
                continue
            fl = py[0]
            if fl not in seen:
                seen.add(fl)
                first_letters.append(fl)
        groups.append(first_letters)
    return groups


def _expand_combinations(groups: list[list[str]]) -> list[str]:
    """对每字首字母集合做笛卡尔积，返回去重后的全部组合。

    Args:
        groups: 每个汉字的首字母集合列表。

    Returns:
        全部首字母组合（去重）。
        例：[[z, c], [y], [t]] → ["zyt", "cyt"]

    举例验证：
        >>> _expand_combinations([['z', 'c'], ['y'], ['t']])
        ['zyt', 'cyt']
    """
    if not groups:
        return []
    result = [""]
    for group in groups:
        if not group:
            continue
        next_: list[str] = []
        for prefix in result:
            for suffix in group:
                next_.append(prefix + suffix)
        result = next_
    # 去重
    seen: set[str] = set()
    out: list[str] = []
    for s in result:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _extract_digits(symbol: str) -> str:
    """symbol 中提取 6 位或 4 位数字。"""
    m = re.match(r"^[shsz](\d{6})$", symbol)
    if m:
        return m.group(1)
    m = re.match(r"^(BK)(\d{4})$", symbol)
    if m:
        return m.group(2)
    return ""


def compute_new_alias(name: str, symbol: str) -> list[str]:
    """按新算法重算 alias，与 atlas `ConvertFromFlinkProfile` 行为一致。"""
    seen: set[str] = set()
    out: list[str] = []

    def add(s: str) -> None:
        if not s or s in seen:
            return
        seen.add(s)
        out.append(s)

    add(name)
    add(symbol)

    digit = _extract_digits(symbol)
    if digit:
        add(digit)

    for combo in _expand_combinations(_initial_groups(name)):
        add(combo)
        add(combo.upper())

    for combo in _expand_combinations(_initial_groups(symbol)):
        add(combo)
        add(combo.upper())

    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="只计算新 alias 不写入 DB")
    args = parser.parse_args()

    print("Loading instruments...", flush=True)
    df = data._query_df("""
        SELECT exchange, symbol, name, alias FROM instrument
        WHERE name IS NOT NULL AND name != ''
    """)
    print(f"  total: {len(df)} rows", flush=True)

    # 计算每行的旧/新 alias
    rows_to_update: list[tuple[Any, ...]] = []
    for _, r in df.iterrows():
        new_alias = compute_new_alias(r["name"], r["symbol"])
        old_alias = list(r["alias"]) if r["alias"] is not None else []
        if set(new_alias) == set(old_alias):
            continue
        rows_to_update.append((new_alias, r["exchange"], r["symbol"]))

    print(f"  rows needing update: {len(rows_to_update)}", flush=True)

    if args.dry_run:
        # 展示一些样本
        for tup in rows_to_update[:5]:
            new_alias, ex, sym = tup
            old_row = df[(df["exchange"] == ex) & (df["symbol"] == sym)].iloc[0]
            print(f"    {ex}:{sym}  name={old_row['name']!r}", flush=True)
            print(f"      old: {list(old_row['alias'])}", flush=True)
            print(f"      new: {new_alias}", flush=True)
        print(f"\n(--dry-run: not written)", flush=True)
        return 0

    if not rows_to_update:
        print("Nothing to update.", flush=True)
        return 0

    # UPDATE 用 executemany 分批提交
    print("Writing...", flush=True)
    with data._get_db() as conn:
        with conn.cursor() as cur:
            for new_alias, ex, sym in rows_to_update:
                cur.execute(
                    "UPDATE instrument SET alias = %s WHERE exchange = %s AND symbol = %s",
                    (psycopg.types.json.Json(new_alias), ex, sym),
                )
        conn.commit()
    print(f"  updated: {len(rows_to_update)} rows", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())