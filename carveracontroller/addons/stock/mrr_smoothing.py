"""Smooths the material removal rate (MRR) over a short stretch of time.

The simulator measures how much material each move removes, but it can only measure
whole grid cells. A cut made of many tiny moves therefore shows up as a few big readings
separated by zeros. Averaging the removed volume over a short time window gives a steady
rate that is the same however the toolpath happens to be split into moves.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

# Long enough to cover several grid cells at typical feed rates, short enough to follow the cut.
MRR_SMOOTH_WINDOW_SEC = 1.0
# Upper limit on how many moves are looked at for one reading, so extremely short moves stay cheap.
_MAX_WALK_STEPS = 5000
# Time spans below this count as zero.
_MIN_SECONDS = 1e-9


def smooth_mrr_series(
    rate: np.ndarray,
    durations: np.ndarray,
    valid: np.ndarray,
    window_sec: float = MRR_SMOOTH_WINDOW_SEC,
    groups: np.ndarray | None = None,
) -> np.ndarray:
    """Return ``rate`` averaged over the last ``window_sec`` seconds of cutting, as float64.

    ``rate`` is the mm³/min of each move, ``durations`` is how many seconds each move
    lasts, and ``valid`` marks the moves that may be averaged together. Moves that are not
    valid (rapids, laser), or have no measured rate (NaN), keep their original value and
    are skipped by the window: they add neither volume nor time, so a retract between two
    passes does not restart the average. ``groups`` (the tool of each move) is optional;
    the window never reaches back past a change of group between two valid moves.
    """
    raw = np.asarray(rate, dtype=np.float64).reshape(-1)
    count = int(raw.shape[0])
    out = raw.copy()
    if count == 0 or not window_sec or window_sec <= 0.0:
        return out

    dur = np.maximum(np.nan_to_num(np.asarray(durations, dtype=np.float64).reshape(-1)[:count]), 0.0)
    if dur.shape[0] < count:
        dur = np.concatenate([dur, np.zeros(count - dur.shape[0])])
    finite = np.asarray(valid, dtype=bool).reshape(-1)[:count]
    if finite.shape[0] < count:
        finite = np.concatenate([finite, np.zeros(count - finite.shape[0], dtype=bool)])
    # Only valid moves with a measured rate take part in the average.
    finite = finite & np.isfinite(raw)
    if not finite.any():
        return out

    volume = np.where(finite, raw, 0.0) * dur / 60.0
    seconds = np.where(finite, dur, 0.0)
    # Running totals of volume against cutting time only. Values between two moves are
    # filled in with a straight line, so the window can start part-way through a move.
    volume_so_far = np.concatenate(([0.0], np.cumsum(volume)))
    cutting_time_so_far = np.concatenate(([0.0], np.cumsum(seconds)))

    # The window never reaches back past the first move after a change of group.
    idx = np.flatnonzero(finite)
    run_begin = np.zeros(idx.shape[0], dtype=bool)
    run_begin[:1] = True
    if groups is not None:
        grp = np.asarray(groups).reshape(-1)[:count]
        if grp.shape[0] < count:
            grp = np.concatenate([grp, np.full(count - grp.shape[0], -1, dtype=grp.dtype)])
        run_begin[1:] = grp[idx][1:] != grp[idx][:-1]
    run_first = np.maximum.accumulate(np.where(run_begin, np.arange(idx.shape[0]), 0))
    run_start = cutting_time_so_far[idx[run_first]]
    end = cutting_time_so_far[idx + 1]
    window_start = np.maximum(end - float(window_sec), run_start)

    delta_volume = volume_so_far[idx + 1] - np.interp(window_start, cutting_time_so_far, volume_so_far)
    delta_seconds = end - window_start
    use = delta_seconds > _MIN_SECONDS
    out[idx[use]] = delta_volume[use] * 60.0 / delta_seconds[use]
    return out


def smooth_mrr_at(
    rate: np.ndarray,
    index: int,
    window_sec: float,
    duration_of: Callable[[int], float],
    is_valid: Callable[[int], bool],
    group_of: Callable[[int], object] | None = None,
) -> float | None:
    """Return the smoothed rate of one move, looking back only as far as the window needs.

    Gives the same answer as :func:`smooth_mrr_series` for that move, without processing
    the whole path. Returns the original value when it cannot be averaged, or None when
    the move has no measured rate.

    ``group_of`` (the tool of a move) is optional. When given, the window stops at the
    first measured move whose group differs from the one at ``index``. Moves that are
    skipped (not valid, or unmeasured) are not compared.
    """
    count = int(rate.shape[0])
    if count == 0:
        return None
    index = max(0, min(int(index), count - 1))
    raw = float(rate[index])
    if raw != raw:
        return None
    if not window_sec or window_sec <= 0.0 or index <= 0 or not is_valid(index):
        return raw

    need = float(window_sec)
    acc_volume = 0.0
    acc_seconds = 0.0
    group = group_of(index) if group_of is not None else None
    j = index
    steps = 0
    while j >= 1 and need > _MIN_SECONDS and steps < _MAX_WALK_STEPS:
        value = float(rate[j])
        if j != index and (value != value or not is_valid(j)):
            # Rapids, laser and unmeasured moves add nothing and do not end the window.
            # They are not counted toward the step cap, so it only limits real cutting moves.
            j -= 1
            continue
        if j != index and group_of is not None and group_of(j) != group:
            break
        steps += 1
        if value == value:
            sec = float(duration_of(j))
            if not math.isfinite(sec) or sec < 0.0:
                sec = 0.0
            take = min(sec, need)
            if take > 0.0:
                acc_volume += value * take / 60.0
                acc_seconds += take
            need -= sec
        j -= 1
    if acc_seconds <= _MIN_SECONDS:
        return raw
    return acc_volume * 60.0 / acc_seconds
