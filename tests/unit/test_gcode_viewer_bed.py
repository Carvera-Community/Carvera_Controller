"""Bed WCS updates should not force a redraw when the origin is unchanged."""

from unittest.mock import MagicMock

from carveracontroller.GcodeViewer import GCodeViewer


def _viewer(**kwargs) -> GCodeViewer:
    viewer = GCodeViewer.__new__(GCodeViewer)
    viewer.bed_visible = True
    viewer._scene_dirty = False
    viewer._bed_wcs_applied = None
    viewer._update_bed_uniforms = MagicMock()
    for key, value in kwargs.items():
        setattr(viewer, key, value)
    return viewer


def test_update_bed_wcs_skips_redraw_when_origin_unchanged():
    origin = (-100.0, -50.0, 1.0, 0.0)
    viewer = _viewer(_bed_wcs_applied=origin)
    viewer._read_bed_wcs_origin = lambda: origin

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_not_called()
    assert viewer._scene_dirty is False


def test_update_bed_wcs_dirties_scene_when_origin_changes():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    viewer._read_bed_wcs_origin = lambda: (-100.0, -50.0, 2.0, 0.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_called_once()
    assert viewer._scene_dirty is True


def test_update_bed_wcs_dirties_scene_when_rotation_changes():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    viewer._read_bed_wcs_origin = lambda: (-100.0, -50.0, 1.0, 90.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_called_once()
    assert viewer._scene_dirty is True


def test_update_bed_wcs_noop_when_bed_hidden():
    viewer = _viewer(bed_visible=False, _bed_wcs_applied=None)
    viewer._read_bed_wcs_origin = lambda: (1.0, 2.0, 3.0, 0.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_not_called()
    assert viewer._scene_dirty is False


def test_bed_wcs_matches_within_epsilon():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.0 + 1e-9, 0.0)) is True
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.01, 0.0)) is False
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.0, 90.0)) is False


def test_read_bed_wcs_origin_removes_tlo_from_z(monkeypatch):
    from carveracontroller.CNC import CNC

    monkeypatch.setitem(CNC.vars, "wcox", -100.0)
    monkeypatch.setitem(CNC.vars, "wcoy", -50.0)
    monkeypatch.setitem(CNC.vars, "wcoz", -20.0)
    monkeypatch.setitem(CNC.vars, "tlo", 12.5)
    monkeypatch.setitem(CNC.vars, "rotation_angle", 0.0)

    assert _viewer()._read_bed_wcs_origin() == (-100.0, -50.0, -32.5, 0.0)


def test_bed_z_does_not_change_with_tool(monkeypatch):
    """Same WCS Z offset, different tool: wcoz moves by the TLO but the bed must not."""
    from carveracontroller.CNC import CNC

    wcs_z = -150.0
    for tlo in (0.0, 12.5, -7.25):
        monkeypatch.setitem(CNC.vars, "wcoz", wcs_z + tlo)
        monkeypatch.setitem(CNC.vars, "tlo", tlo)
        assert _viewer()._read_bed_wcs_origin()[2] == wcs_z
