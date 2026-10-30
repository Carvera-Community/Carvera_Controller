"""Monitoring graph colors follow the theme, and the backdrop matches the 3D viewer."""

from carveracontroller.ui.themes import load_palette, theme_names

_GRAPH_TOKENS = (
    "graph_bg",
    "graph_line_1",
    "graph_line_2",
    "graph_axis",
    "graph_spine",
    "graph_panel",
    "graph_cursor",
)


def test_every_theme_defines_the_monitoring_graph_colors():
    for name in theme_names():
        palette = load_palette(name)
        missing = [token for token in _GRAPH_TOKENS if token not in palette]
        assert missing == [], name


def test_graph_background_matches_the_viewer_backdrop():
    for name in theme_names():
        palette = load_palette(name)
        assert palette["graph_bg"] == palette["bg"], name
