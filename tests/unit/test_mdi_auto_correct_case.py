"""Tests for MDI auto-correct case feature.

When enabled, command tokens typed into the MDI are corrected to the
canonical case defined in the intellisense command catalog before being
sent to the firmware (which is case-sensitive). Parameter words are
corrected only when that command defines them.
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from carveracontroller.addons.intellisense.engine import (
    CommandCatalog,
    correct_command_case,
)

# ---------------------------------------------------------------------------
# Engine: correct_command_case
# ---------------------------------------------------------------------------


@pytest.fixture()
def catalog():
    return CommandCatalog.from_path()


class TestCorrectCommandCase:
    def test_gcode_uppercase_passthrough(self, catalog):
        assert correct_command_case("G0 X10 Y20", catalog) == "G0 X10 Y20"

    def test_gcode_lowercase_corrected(self, catalog):
        assert correct_command_case("g0 X10 Y20", catalog) == "G0 X10 Y20"

    def test_mcode_lowercase_corrected(self, catalog):
        assert correct_command_case("m3 S1000", catalog) == "M3 S1000"

    def test_mixed_case_gm_corrected(self, catalog):
        assert correct_command_case("g1 x10 m3 s500", catalog) == "G1 X10 M3 S500"

    def test_defined_parameters_corrected(self, catalog):
        assert correct_command_case("g0 x10 f1", catalog) == "G0 X10 F1"

    def test_undefined_parameter_unchanged(self, catalog):
        assert correct_command_case("g0 q5", catalog) == "G0 q5"

    def test_parameter_in_comment_unchanged(self, catalog):
        assert correct_command_case("g0 x10 (move x20)", catalog) == "G0 X10 (move x20)"

    def test_packed_parameters_corrected(self, catalog):
        assert correct_command_case("g0x10f1", catalog) == "G0X10F1"

    def test_shell_command_corrected(self, catalog):
        assert correct_command_case("LS -e -s /sd", catalog) == "ls -e -s /sd"

    def test_shell_parameter_case_corrected(self, catalog):
        assert correct_command_case("LS -E -S /sd", catalog) == "ls -e -s /sd"

    def test_dollar_command_corrected(self, catalog):
        result = correct_command_case("$h", catalog)
        assert result == "$H"

    def test_empty_line_unchanged(self, catalog):
        assert correct_command_case("", catalog) == ""
        assert correct_command_case("   ", catalog) == "   "

    def test_unknown_command_unchanged(self, catalog):
        assert correct_command_case("ZZZZZ123", catalog) == "ZZZZZ123"

    def test_comment_only_line(self, catalog):
        assert correct_command_case("(this is a comment)", catalog) == "(this is a comment)"

    def test_preserves_whitespace(self, catalog):
        result = correct_command_case("  g0  X10", catalog)
        assert result.startswith("  ")
        assert "G0" in result

    def test_multiword_gcode_line(self, catalog):
        result = correct_command_case("g0 X10 g1 Y20 F100", catalog)
        assert "G0" in result
        assert "G1" in result

    def test_zero_padded_gcode(self, catalog):
        result = correct_command_case("g01 X10", catalog)
        assert "G1" in result

    def test_g10_not_clobbered_by_g1(self, catalog):
        """G10 must not be partially replaced when G1 is also on the line."""
        result = correct_command_case("g10 L20 P0 X0 g1 X10 F100", catalog)
        assert result.startswith("G10")
        assert "G1 " in result or result.endswith("G1")

    def test_packed_gcode_tokens(self, catalog):
        result = correct_command_case("g90g0 X10", catalog)
        assert "G90" in result
        assert "G0" in result


# ---------------------------------------------------------------------------
# Integration: send_cmd respects mdi_auto_correct_case
# ---------------------------------------------------------------------------


def _root(widget):
    return SimpleNamespace(
        manual_cmd=widget,
        manual_rv=SimpleNamespace(scroll_y=1, data=[]),
        controller=SimpleNamespace(executeCommand=Mock()),
        refocus_cmd=Mock(),
        mdi_auto_correct_case=True,
    )


def test_send_cmd_corrects_case_when_enabled():
    from carveracontroller.main import Makera, MDITextInput

    widget = MDITextInput()
    root = _root(widget)
    root.mdi_auto_correct_case = True
    widget.text = "g0 x10 f1"

    with (
        patch("carveracontroller.main.hide_mdi_intellisense"),
        patch("carveracontroller.main.Clock.schedule_once"),
    ):
        Makera.send_cmd(root)

    sent = root.controller.executeCommand.call_args[0][0]
    assert sent == "G0 X10 F1"


def test_send_cmd_does_not_correct_case_when_disabled():
    from carveracontroller.main import Makera, MDITextInput

    widget = MDITextInput()
    root = _root(widget)
    root.mdi_auto_correct_case = False
    widget.text = "g0 X10"

    with (
        patch("carveracontroller.main.hide_mdi_intellisense"),
        patch("carveracontroller.main.Clock.schedule_once"),
    ):
        Makera.send_cmd(root)

    sent = root.controller.executeCommand.call_args[0][0]
    assert sent == "g0 X10"


def test_send_cmd_corrects_multiline():
    from carveracontroller.main import Makera, MDITextInput

    widget = MDITextInput()
    root = _root(widget)
    root.mdi_auto_correct_case = True
    widget.text = "g0 x10 f1\nm3 s1000"

    with (
        patch("carveracontroller.main.hide_mdi_intellisense"),
        patch("carveracontroller.main.Clock.schedule_once"),
    ):
        Makera.send_cmd(root)

    sent = root.controller.executeCommand.call_args[0][0]
    assert sent.split("\n") == ["G0 X10 F1", "M3 S1000"]
