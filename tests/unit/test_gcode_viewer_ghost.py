"""Ghost toolpath display option."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from carveracontroller.GcodeViewer import (
    CONFIG_GHOST_PATHS_KEY,
    PATH_GHOST_ALPHA,
    PATH_GHOST_RECENT_ALPHA,
    PATH_GHOST_RECENT_PART_FRACTION,
    GCodeViewer,
    bbox_diagonal,
)

SHADER_PATH = Path(__file__).parents[2] / "carveracontroller" / "shaders" / "toolpath.glsl"


def test_toolpath_shader_fades_recent_ghost_paths():
    shader = SHADER_PATH.read_text()

    assert "uniform float path_alpha;" in shader
    assert "uniform float path_alpha_recent;" in shader
    assert "uniform float path_fade_now;" in shader
    assert "uniform float path_fade_span;" in shader
    assert "mix(path_alpha, path_alpha_recent, t)" in shader
    assert "t * t * t" in shader
    assert "vec4(color, alpha)" in shader


def test_bbox_diagonal_is_zero_when_empty():
    assert bbox_diagonal([float("inf")] * 3, [float("-inf")] * 3) == 0.0
    assert bbox_diagonal([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) == 0.0


def _meshmanager(min_pt=(0.0, 0.0, 0.0), max_pt=(3.0, 4.0, 0.0), position_scale=2.0):
    # Unscaled 3-4-5 triangle; scaled diagonal is 10 unless overridden.
    return SimpleNamespace(min_pt=list(min_pt), max_pt=list(max_pt), position_scale=position_scale)


def _ghost_viewer(**kwargs) -> GCodeViewer:
    viewer = GCodeViewer.__new__(GCodeViewer)
    viewer.linemesh = {}
    viewer._path_ghosted = False
    viewer._scene_dirty = False
    viewer.lengths = [0.0, 50.0, 100.0]
    viewer.display_count = 100.0
    viewer.meshmanager = _meshmanager()
    for key, value in kwargs.items():
        setattr(viewer, key, value)
    return viewer


def _scaled_part_span(viewer) -> float:
    return (
        bbox_diagonal(viewer.meshmanager.min_pt, viewer.meshmanager.max_pt)
        * float(viewer.meshmanager.position_scale)
        * PATH_GHOST_RECENT_PART_FRACTION
    )


@patch("carveracontroller.GcodeViewer.Config")
def test_set_path_ghosted_sets_alpha_uniform(config):
    viewer = _ghost_viewer()

    viewer.set_path_ghosted(True)

    assert viewer.is_path_ghosted() is True
    assert viewer.linemesh["path_alpha"] == PATH_GHOST_ALPHA
    assert viewer.linemesh["path_alpha_recent"] == PATH_GHOST_RECENT_ALPHA
    config.set.assert_called_once_with("carvera", CONFIG_GHOST_PATHS_KEY, "1")
    config.write.assert_called_once()
    assert viewer._scene_dirty is True

    viewer.set_path_ghosted(False)

    assert viewer.is_path_ghosted() is False
    assert viewer.linemesh["path_alpha"] == 1.0
    assert viewer.linemesh["path_alpha_recent"] == 1.0
    config.set.assert_called_with("carvera", CONFIG_GHOST_PATHS_KEY, "0")


@patch("carveracontroller.GcodeViewer.Config")
def test_set_path_ghosted_is_noop_when_unchanged(config):
    viewer = _ghost_viewer(
        _path_ghosted=True,
        linemesh={"path_alpha": PATH_GHOST_ALPHA, "path_alpha_recent": PATH_GHOST_RECENT_ALPHA},
    )

    viewer.set_path_ghosted(True)

    config.set.assert_not_called()
    config.write.assert_not_called()
    assert viewer.linemesh["path_alpha"] == PATH_GHOST_ALPHA
    assert viewer._scene_dirty is False


@patch("carveracontroller.GcodeViewer.Config")
def test_ghost_fade_follows_playhead(config):
    viewer = _ghost_viewer(display_count=40.0)

    viewer.set_path_ghosted(True)

    assert viewer.linemesh["path_fade_now"] == pytest.approx(40.0)
    assert viewer.linemesh["path_fade_span"] == pytest.approx(_scaled_part_span(viewer))


@patch("carveracontroller.GcodeViewer.Config")
def test_ghost_fade_uses_full_path_when_shader_shows_all(config):
    viewer = _ghost_viewer(display_count=0.0, linemesh={"display_count": -1.0})

    viewer.set_path_ghosted(True)

    assert viewer.linemesh["path_fade_now"] == pytest.approx(100.0)
    assert viewer.linemesh["path_fade_span"] == pytest.approx(_scaled_part_span(viewer))


@patch("carveracontroller.GcodeViewer.Config")
def test_ghost_fade_span_matches_scaled_part_diagonal(config):
    viewer = _ghost_viewer()

    viewer.set_path_ghosted(True)

    assert viewer.linemesh["path_fade_span"] == pytest.approx(_scaled_part_span(viewer))


@patch("carveracontroller.GcodeViewer.Config")
def test_ghost_fade_span_does_not_grow_with_program_length(config):
    bbox = _meshmanager()
    short = _ghost_viewer(display_count=40.0, meshmanager=bbox, lengths=[0.0, 40.0])
    long = _ghost_viewer(display_count=400.0, meshmanager=bbox, lengths=[0.0, 400.0])

    short.set_path_ghosted(True)
    long.set_path_ghosted(True)

    assert short.linemesh["path_fade_span"] == pytest.approx(long.linemesh["path_fade_span"])
    assert long.linemesh["path_fade_span"] == pytest.approx(_scaled_part_span(long))


@patch("carveracontroller.GcodeViewer.Config")
def test_ghost_fade_span_clamps_to_playhead(config):
    viewer = _ghost_viewer(display_count=2.0)

    viewer.set_path_ghosted(True)

    assert viewer.linemesh["path_fade_span"] == pytest.approx(2.0)
