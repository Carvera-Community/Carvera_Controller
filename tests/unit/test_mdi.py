"""Tests for MDI input validation against machine buffer limits."""

from carveracontroller.machine.mdi import MDI_MAX_LINE_BYTES, prepare_mdi_lines


class TestPrepareMdiLines:
    def test_single_line_passes_through(self):
        assert prepare_mdi_lines("G0 X10") == (["G0 X10"], [])

    def test_multiline_input_splits_into_individual_lines(self):
        lines, rejected = prepare_mdi_lines("G21\nG90\nG0 X10 Y10")
        assert lines == ["G21", "G90", "G0 X10 Y10"]
        assert rejected == []

    def test_blank_and_whitespace_lines_are_dropped(self):
        lines, rejected = prepare_mdi_lines("G21\n\n   \nG90\n")
        assert lines == ["G21", "G90"]
        assert rejected == []

    def test_crlf_input_splits_without_stray_carriage_returns(self):
        lines, _ = prepare_mdi_lines("G21\r\nG90\r\n")
        assert lines == ["G21", "G90"]

    def test_lines_are_stripped(self):
        lines, _ = prepare_mdi_lines("  G0 X1  \n\tG0 Y1\t")
        assert lines == ["G0 X1", "G0 Y1"]

    def test_line_at_limit_is_accepted(self):
        line = "M117 " + "a" * (MDI_MAX_LINE_BYTES - 5)
        assert len(line.encode("utf-8")) == MDI_MAX_LINE_BYTES
        lines, rejected = prepare_mdi_lines(line)
        assert lines == [line]
        assert rejected == []

    def test_line_over_limit_is_rejected(self):
        line = "M117 " + "a" * MDI_MAX_LINE_BYTES
        lines, rejected = prepare_mdi_lines(line)
        assert lines == []
        assert rejected == [line]

    def test_limit_is_measured_in_utf8_bytes_not_characters(self):
        # ç encodes to two UTF-8 bytes: 200 chars -> 400 bytes, over the limit
        line = "ç" * 200
        assert len(line) < MDI_MAX_LINE_BYTES
        lines, rejected = prepare_mdi_lines(line)
        assert lines == []
        assert rejected == [line]

    def test_rejection_keeps_valid_lines(self):
        long_line = "b" * (MDI_MAX_LINE_BYTES + 1)
        lines, rejected = prepare_mdi_lines(f"G21\n{long_line}\nG90")
        assert lines == ["G21", "G90"]
        assert rejected == [long_line]

    def test_empty_input_returns_nothing(self):
        assert prepare_mdi_lines("") == ([], [])
        assert prepare_mdi_lines("   \n  ") == ([], [])
