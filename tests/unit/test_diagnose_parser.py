"""Diagnose ({...}) status parsing, including RSSI."""

from carveracontroller.CNC import CNC
from carveracontroller.Controller import Controller
from carveracontroller.protocols.framing import PTYPE_DIAG_RES, build_frame
from carveracontroller.protocols.session import ProtocolSession


def test_comms_strips_trailing_newline_from_diagnose_payload():
    session = ProtocolSession()
    session.select("makera")
    # Firmware get_diagnose_string() ends with "}\\n"; framing includes that payload.
    frame = build_frame(PTYPE_DIAG_RES, b"{S:0,5000|RSSI:-57}\n")
    msgs = session.feed(frame)
    assert len(msgs) == 1
    assert msgs[0].text == "{S:0,5000|RSSI:-57}"


def test_diagnose_rssi_field():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{S:0,5000|L:0,0|F:1,0|V:0,1|G:0|T:0|R:0|I:0|RSSI:-57}")
    assert CNC.vars["sw_spindle"] == 0
    assert CNC.vars["st_e_stop"] == 0
    assert CNC.vars["RSSI"] == -57


def test_diagnose_estop_pin_engaged():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{S:0,5000|I:1|RSSI:-57}")
    assert CNC.vars["st_e_stop"] == 1


def test_diagnose_with_junk_after_brace():
    ctrl = Controller(CNC(), lambda _line: None, False)
    ctrl.parseBigParentheses("{S:1,1000|RSSI:-40}\x00")
    assert CNC.vars["sw_spindle"] == 1
    assert CNC.vars["RSSI"] == -40
