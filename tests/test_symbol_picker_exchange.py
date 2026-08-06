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


def test_as_all_add_returns_real_exchange(at):
    at.run()
    at.selectbox(key="test_picker_exchange").set_value("as_all")
    at.run()

    options = at.selectbox(key="test_picker_symbol_select").options
    assert [option.split("_", 1)[0] for option in options] == [
        "as:600519",
        "asindex:sh000300",
        "ths:600519",
    ]
    at.selectbox(key="test_picker_symbol_select").set_value("as:600519")
    at.button(key="test_picker_add").click().run()

    assert at.session_state["picker_result"] == ("as", "600519")
    assert "as_all" not in repr(at.session_state["picker_result"])


def test_real_exchange_selection_returns_same_exchange(at):
    at.run()
    at.selectbox(key="test_picker_exchange").set_value("ths")
    at.run()
    at.selectbox(key="test_picker_symbol_select").set_value("600519")
    at.button(key="test_picker_add").click().run()

    assert at.session_state["picker_result"] == ("ths", "600519")


def test_as_all_result_encodes_to_real_kline_token():
    token = encode_symbol_token("as", "600519", "1d")

    assert token == "as:600519:1d"
    assert "as_all" not in token


def test_real_exchange_result_builds_real_flight_tag():
    tags = build_kline_tags(["600519"], "as", "1d")

    assert tags == ["as_600519_1d"]
    assert tags != ["as_all_600519_1d"]
