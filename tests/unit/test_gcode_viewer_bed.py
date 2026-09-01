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
    viewer._read_wcs_origin = lambda: origin

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_not_called()
    assert viewer._scene_dirty is False


def test_update_bed_wcs_dirties_scene_when_origin_changes():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    viewer._read_wcs_origin = lambda: (-100.0, -50.0, 2.0, 0.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_called_once()
    assert viewer._scene_dirty is True


def test_update_bed_wcs_dirties_scene_when_rotation_changes():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    viewer._read_wcs_origin = lambda: (-100.0, -50.0, 1.0, 90.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_called_once()
    assert viewer._scene_dirty is True


def test_update_bed_wcs_noop_when_bed_hidden():
    viewer = _viewer(bed_visible=False, _bed_wcs_applied=None)
    viewer._read_wcs_origin = lambda: (1.0, 2.0, 3.0, 0.0)

    viewer.update_bed_wcs()

    viewer._update_bed_uniforms.assert_not_called()
    assert viewer._scene_dirty is False


def test_bed_wcs_matches_within_epsilon():
    viewer = _viewer(_bed_wcs_applied=(-100.0, -50.0, 1.0, 0.0))
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.0 + 1e-9, 0.0)) is True
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.01, 0.0)) is False
    assert viewer._bed_wcs_matches((-100.0, -50.0, 1.0, 90.0)) is False
