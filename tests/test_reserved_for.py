"""The phrase shown when the board is reserved (mode "project") is configurable, not hardcoded to the GPGPU."""
from __future__ import annotations

from web_api.config import WebApiConfig

from tests.test_public_board import PORTFOLIO, make_board


def test_default_reserved_for_is_generic():
    assert WebApiConfig().reserved_for == "owner projects"


def test_config_reads_reserved_for_from_env(monkeypatch):
    monkeypatch.setenv("WEB_API_RESERVED_FOR", "thesis work")
    assert WebApiConfig.from_env().reserved_for == "thesis work"


def test_board_payloads_carry_reserved_for():
    board = make_board(WebApiConfig(board_label="Smart Zynq SL", public_cors_origins=(PORTFOLIO,), reserved_for="thesis work"))
    assert board._public_board()["reserved_for"] == "thesis work"
    assert board._public_board()["label"] == "Smart Zynq SL"
    assert board.public_snapshot()["reserved_for"] == "thesis work"
    board.fpga_state = None
    assert board.public_snapshot()["reserved_for"] == "thesis work"
