"""Metric choices for the File-page monitoring graph."""

from __future__ import annotations

from dataclasses import dataclass

from kivy.factory import Factory
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.translation import tr

GRAPH_METRIC_NONE = "none"
GRAPH_METRIC_DEFAULT_LINE1 = "temp"
GRAPH_METRIC_DEFAULT_LINE2 = "spindle_rpm"
GRAPH_DEFAULT_TIME_RANGE = 300
GRAPH_DEFAULT_GRANULARITY = 0.2
GRAPH_TIME_RANGES = (30, 60, 300, 900)
GRAPH_GRANULARITIES = (0.2, 1, 5, 30)


@dataclass(frozen=True)
class GraphMetric:
    key: str
    label: str
    cnc_var: str | None
    ylabel: str
    ymin: float
    ymax: float
    computed: bool = False

    @property
    def visible(self) -> bool:
        return self.cnc_var is not None or self.computed


GRAPH_METRICS = (
    GraphMetric(GRAPH_METRIC_NONE, "None", None, "", 0.0, 1.0),
    GraphMetric("temp", "Temp", "spindletemp", "Temp (°C)", 20.0, 60.0),
    GraphMetric("spindle_rpm", "Spindle RPM", "curspindle", "Spindle RPM", 3000.0, 12000.0),
    GraphMetric("target_rpm", "Target RPM", "tarspindle", "Target RPM", 3000.0, 12000.0),
    GraphMetric(
        "rpm_deviation",
        "RPM deviation (%)",
        None,
        "RPM deviation (%)",
        -5.0,
        5.0,
        computed=True,
    ),
    GraphMetric("feed", "Feed", "curfeed", "Feed", 100.0, 1000.0),
)

GRAPH_METRICS_BY_KEY = {metric.key: metric for metric in GRAPH_METRICS}


def graph_metric_choices() -> list[str]:
    return [tr._(metric.label) for metric in GRAPH_METRICS]


def graph_metric_label(key: str) -> str:
    metric = GRAPH_METRICS_BY_KEY.get(key, GRAPH_METRICS_BY_KEY[GRAPH_METRIC_NONE])
    return tr._(metric.label)


def graph_metric_key_from_label(label: str) -> str:
    for metric in GRAPH_METRICS:
        if label in (tr._(metric.label), metric.label):
            return metric.key
    return GRAPH_METRIC_NONE


def graph_metric_ylim(key: str, samples: list[float] | tuple[float, ...] | None = None) -> tuple[float, float]:
    """Return the axis range, expanding the default min/max if samples fall outside it."""
    metric = GRAPH_METRICS_BY_KEY.get(key, GRAPH_METRICS_BY_KEY[GRAPH_METRIC_NONE])
    ymin, ymax = metric.ymin, metric.ymax
    if samples:
        ymin = min(ymin, min(samples))
        ymax = max(ymax, max(samples))
    return ymin, ymax


def graph_number_label(value: float | int) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return str(number)


def graph_number_choices(values: tuple[float, ...] | list[float]) -> list[str]:
    return [graph_number_label(value) for value in values]


def graph_number_from_label(label: str, allowed: tuple[float, ...] | list[float]) -> float | None:
    try:
        parsed = float(label)
    except (TypeError, ValueError):
        return None
    for option in allowed:
        if abs(float(option) - parsed) < 1e-9:
            return float(option)
    return None


class GraphControls(BoxLayout):
    """Top-right graph overlay. Width stays 250dp so opening only grows down."""

    adjust_open = BooleanProperty(False)
    line1_metric = StringProperty("")
    line2_metric = StringProperty("")
    time_range = NumericProperty(GRAPH_DEFAULT_TIME_RANGE)
    granularity = NumericProperty(GRAPH_DEFAULT_GRANULARITY)
    metric_choices = ListProperty([])

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.metric_choices:
            self.metric_choices = graph_metric_choices()
        self.bind(size=self._reanchor)

    def on_parent(self, _instance, parent):
        if parent is not None:
            parent.bind(pos=self._reanchor, size=self._reanchor)
        self._reanchor()

    def _reanchor(self, *_args):
        parent = self.parent
        if parent is None:
            return
        margin = dp(4)
        self.right = parent.right - margin
        self.top = parent.top - margin

    def collide_point(self, x, y):
        if not super().collide_point(x, y):
            return False
        if self.adjust_open:
            return True
        return x >= self.right - dp(25)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        for child in self.children[:]:
            # Collapsed settings still layout their spinners; skip them so the
            # gear click is not stolen by the hidden Granularity dropdown.
            if not self.adjust_open and not getattr(child, "visible", True):
                continue
            if child.dispatch("on_touch_down", touch):
                return True
        return self.adjust_open


Factory.register("GraphControls", cls=GraphControls)
