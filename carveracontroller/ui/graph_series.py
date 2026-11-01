"""Derived monitoring-graph samples that are not a single status field."""

from __future__ import annotations

import math


def format_graph_value(value: float) -> str:
    """Plain decimal text for hover labels and tick marks.

    Matplotlib's default short formatter prints modest RPM values in scientific
    notation (``5e+02``). Whole numbers stay integers; smaller values keep one
    or two decimal places.
    """
    number = float(value)
    if not math.isfinite(number):
        return ""
    magnitude = abs(number)
    if magnitude >= 100 or number.is_integer():
        return f"{number:.0f}"
    if magnitude >= 10:
        return f"{number:.1f}"
    return f"{number:.2f}"


def rpm_deviation_percent(actual_rpm: float, target_rpm: float) -> float:
    """Signed percent by which actual spindle speed differs from the request.

    Zero when no speed was requested, so a stopped spindle does not divide by zero.
    """
    target = float(target_rpm)
    if target == 0.0:
        return 0.0
    return (float(actual_rpm) - target) / target * 100.0
