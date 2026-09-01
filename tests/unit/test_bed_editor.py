"""Bed editor field helpers (no Kivy widget tree)."""

import pytest

from carveracontroller.addons.beds.ui.BedEditorPopup import (
    _optional_mm_text,
    _parse_finite_float,
)


def test_optional_mm_text_blank_until_user_types():
    assert _optional_mm_text(None) == ""


def test_optional_mm_text_keeps_zero_and_negatives():
    assert _optional_mm_text(0) == "0"
    assert _optional_mm_text(0.0) == "0"
    assert _optional_mm_text(-111.5) == "-111.5"


def test_machine_z_empty_is_required():
    with pytest.raises(ValueError):
        _parse_finite_float("  ", "Machine Z")


def test_machine_z_accepts_typed_zero():
    assert _parse_finite_float("0", "Machine Z") == 0.0
    assert _parse_finite_float("-108.3", "Machine Z") == -108.3
