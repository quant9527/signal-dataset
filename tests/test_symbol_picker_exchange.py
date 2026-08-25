"""交易所选择器默认值与聚合 exchange 边界测试。"""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from flight_kline_client import build_kline_tags
from symbol_picker import encode_symbol_token


RUNNER_TEMPLATE = r'''
import pandas as pd
import streamlit as st

import data


def fake_get_instruments_by_exchange(exchange):
    frames = {
        "as": pd.DataFrame({
            "exchange": ["as"],
            "symbol": ["600519"],
            "name": ["贵州茅台"],
            "sub_exchange": ["sh"],
            "alias": [["gzmt"]],
        }),
        "ths": pd.DataFrame({
            "exchange": ["ths"],
            "symbol": ["600519"],
            "name": ["贵州茅台同花顺"],
            "sub_exchange": ["sh"],
            "alias": [["gzmt_ths"]],
        }),
        "asindex": pd.DataFrame({
            "exchange": ["asindex"],
            "symbol": ["sh000300"],
            "name": ["沪深300"],
            "sub_exchange": ["sh"],
            "alias": [["hs300"]],
        }),
        "binance": pd.DataFrame({
            "exchange": ["binance"],
            "symbol": ["BTCUSDT"],
            "name": ["比特币"],
            "sub_exchange": [""],
            "alias": [["btc"]],
        }),
        "hyperliquid": pd.DataFrame({
            "exchange": ["hyperliquid"],
            "symbol": ["ETH"],
            "name": ["以太坊"],
            "sub_exchange": [""],
            "alias": [["eth"]],
        }),
    }
    return frames.get(exchange, pd.DataFrame())


data.get_instruments_by_exchange = fake_get_instruments_by_exchange

import symbol_picker

symbol_picker.get_instruments_by_exchange = fake_get_instruments_by_exchange

result = symbol_picker.symbol_picker_add_ui(key_prefix="test_picker")
if result is not None:
    st.session_state["picker_result"] = result
'''


@pytest.fixture
def at(tmp_path):
    runner = tmp_path / "exchange_runner.py"
    runner.write_text(RUNNER_TEMPLATE)
    return AppTest.from_file(str(runner))


def test_exchange_defaults_to_as_all(at):
    at.run()

    exchange = at.selectbox(key="test_picker_exchange")
    assert exchange.value == "as_all"


def test_symbol_defaults_to_placeholder(at):
    """首次加载时 selectbox 默认是占位项，而不是按字典序排第一的真实标的。"""
    at.run()

    sym = at.selectbox(key="test_picker_symbol_select")
    assert sym.value == "__placeholder__"


def test_first_load_does_not_emit_picker_result(at):
    """首次加载默认是占位项，不应触发任何 (exchange, symbol) 返回。"""
    at.run()

    assert "picker_result" not in at.session_state


def test_placeholder_options_come_before_real_symbols(at):
    at.run()

    # AppTest 渲染后的 options 是 format_func 处理过的展示文本
    options = at.selectbox(key="test_picker_symbol_select").options
    assert options[0] == "— 请选择代码 —"
    # 真实标的按字母序排列
    assert options[1:] == [
        "as:600519_贵州茅台_gzmt",
        "asindex:sh000300_沪深300_hs300",
        "ths:600519_贵州茅台同花顺_gzmt_ths",
    ]


def test_as_all_add_returns_real_exchange(at):
    at.run()
    at.selectbox(key="test_picker_exchange").set_value("as_all")
    at.run()

    options = at.selectbox(key="test_picker_symbol_select").options
    assert options[0] == "— 请选择代码 —"
    # 选一个真实的 symbol，触发添加
    at.selectbox(key="test_picker_symbol_select").set_value("ths:600519")
    at.run()

    assert at.session_state["picker_result"] == ("ths", "600519")
    assert "as_all" not in repr(at.session_state["picker_result"])


def test_crypto_add_returns_real_exchange(at):
    at.run()
    at.selectbox(key="test_picker_exchange").set_value("crypto")
    at.run()

    options = at.selectbox(key="test_picker_symbol_select").options
    assert options[0] == "— 请选择代码 —"
    # crypto 合集应同时包含 binance 与 hyperliquid 的标的
    assert "binance:BTCUSDT_比特币_btc" in options
    assert "hyperliquid:ETH_以太坊" in options

    # 选一个真实的 binance 标的，触发添加
    at.selectbox(key="test_picker_symbol_select").set_value("binance:BTCUSDT")
    at.run()

    assert at.session_state["picker_result"] == ("binance", "BTCUSDT")
    assert "crypto" not in repr(at.session_state["picker_result"])


def test_real_exchange_selection_returns_same_exchange(at):
    # 首次 run：默认占位项；不触发添加
    at.run()
    assert "picker_result" not in at.session_state

    # 用户切到 ths：默认仍是占位项，依然不触发添加（避免切换交易所就意外添加）
    at.selectbox(key="test_picker_exchange").set_value("ths")
    at.run()
    assert "picker_result" not in at.session_state

    # 用户在 ths 下选 600519：触发添加
    at.selectbox(key="test_picker_symbol_select").set_value("600519")
    at.run()

    assert at.session_state["picker_result"] == ("ths", "600519")


def test_as_all_result_encodes_to_real_kline_token():
    token = encode_symbol_token("as", "600519", "1d")

    assert token == "as:600519:1d"
    assert "as_all" not in token


def test_real_exchange_result_builds_real_flight_tag():
    tags = build_kline_tags(["600519"], "as", "1d")

    assert tags == ["as_600519_1d"]
    assert tags != ["as_all_600519_1d"]
