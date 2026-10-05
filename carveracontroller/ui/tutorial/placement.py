"""Card and spotlight geometry. Units are whatever the caller passes in."""

from __future__ import annotations

from dataclasses import dataclass

MARGIN = 12.0
GAP = 12.0
MIN_HOLE = 28.0
HOLE_PAD = 4.0
BUTTON_ROW_H = 48.0
PREFERRED_CARD = (320.0, 200.0)
COMPACT_WIDTH = 720.0
SHORT_HEIGHT = 640.0
MIN_DOCK_BAND = 96.0


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def right(self) -> float:
        return self.x + self.w

    def top(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class Placement:
    card: Rect
    hole: Rect | None
    docked: bool
    body_scrolls: bool
    button_row: Rect


def _union_pair(a: Rect, b: Rect) -> Rect:
    x0 = min(a.x, b.x)
    y0 = min(a.y, b.y)
    x1 = max(a.right(), b.right())
    y1 = max(a.top(), b.top())
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _intersects(a: Rect, b: Rect) -> bool:
    return not (a.right() <= b.x or b.right() <= a.x or a.top() <= b.y or b.top() <= a.y)


def _contains(outer: Rect, inner: Rect) -> bool:
    return (
        inner.x >= outer.x - 0.5
        and inner.y >= outer.y - 0.5
        and inner.right() <= outer.right() + 0.5
        and inner.top() <= outer.top() + 0.5
    )


def _usable(window_width: float, window_height: float, safe: tuple[float, float, float, float], margin: float) -> Rect:
    # safe is left, top, right, bottom — the same order as MakeraApp.safe_area_padding.
    left = safe[0] + margin
    top_inset = safe[1] + margin
    right_inset = safe[2] + margin
    bottom = safe[3] + margin
    return Rect(
        left,
        bottom,
        max(0.0, window_width - left - right_inset),
        max(0.0, window_height - top_inset - bottom),
    )


def _clamp(rect: Rect, bounds: Rect) -> Rect:
    x = min(max(rect.x, bounds.x), bounds.right())
    y = min(max(rect.y, bounds.y), bounds.top())
    right = min(max(rect.right(), bounds.x), bounds.right())
    top = min(max(rect.top(), bounds.y), bounds.top())
    return Rect(x, y, max(0.0, right - x), max(0.0, top - y))


def merge_overlapping_holes(holes: tuple[Rect, ...] | list[Rect], slack: float = 2.0) -> list[Rect]:
    """Join spotlight rects whose outlines would cross.

    Adjacent toolbar buttons are only a few pixels apart. Padding each one
    makes those outlines overlap, so a touching run becomes one rectangle.
    """
    groups = list(holes)
    changed = True
    while changed:
        changed = False
        pending = groups
        groups = []
        for hole in pending:
            for index, group in enumerate(groups):
                grown = Rect(group.x - slack, group.y - slack, group.w + 2 * slack, group.h + 2 * slack)
                if _intersects(grown, hole):
                    groups[index] = _union_pair(group, hole)
                    changed = True
                    break
            else:
                groups.append(hole)
    return groups


def spotlight_hole(
    target: Rect,
    *,
    window_width: float,
    window_height: float,
    min_size: float = MIN_HOLE,
    pad: float = HOLE_PAD,
) -> Rect:
    """Pad the target and grow it to a minimum so a shrunken button stays visible."""
    padded = Rect(target.x - pad, target.y - pad, target.w + 2 * pad, target.h + 2 * pad)
    width = max(padded.w, min_size)
    height = max(padded.h, min_size)
    cx = padded.x + padded.w / 2.0
    cy = padded.y + padded.h / 2.0
    hole = Rect(cx - width / 2.0, cy - height / 2.0, width, height)
    return _clamp(hole, Rect(0.0, 0.0, window_width, window_height))


def place_banner(
    window_width: float,
    window_height: float,
    safe: tuple[float, float, float, float],
    hole: Rect | None,
    height: float,
) -> Rect:
    """A full-width strip at the top, or at the bottom when the top would cover the hole."""
    width = max(0.0, window_width - safe[0] - safe[2])
    top_y = window_height - safe[1] - height
    banner = Rect(safe[0], top_y, width, height)
    if hole is not None and _intersects(banner, hole):
        banner = Rect(safe[0], safe[3], width, height)
    return banner


def _pack(card: Rect, hole: Rect | None, *, docked: bool, preferred_h: float) -> Placement:
    row_h = min(BUTTON_ROW_H, card.h)
    button_row = Rect(card.x, card.y, card.w, row_h)
    return Placement(
        card=card,
        hole=hole,
        docked=docked,
        body_scrolls=card.h + 0.5 < preferred_h,
        button_row=button_row,
    )


def _vertical_slot(
    usable: Rect,
    holes: tuple[Rect, ...],
    x: float,
    card_w: float,
    gap: float,
    prefer_center: float,
    min_h: float,
    pref_h: float,
) -> tuple[float, float] | None:
    """``(y, height)`` inside ``usable`` that clears holes overlapping this x.

    The height is as close to ``pref_h`` as the free band allows, and never
    shorter than ``min_h``.
    """
    blocked: list[tuple[float, float]] = []
    right = x + card_w
    for hole in holes:
        if hole.x - gap >= right or hole.right() + gap <= x:
            continue
        blocked.append((hole.y - gap, hole.top() + gap))
    blocked.sort()
    merged: list[tuple[float, float]] = []
    for start, end in blocked:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    free: list[tuple[float, float]] = []
    cursor = usable.y
    for start, end in merged:
        if start > cursor:
            free.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < usable.top():
        free.append((cursor, usable.top()))
    best: tuple[tuple[float, float], float, float] | None = None
    for start, end in free:
        room = end - start
        if room < min_h:
            continue
        height = min(pref_h, room)
        y = min(max(prefer_center - height / 2.0, start), end - height)
        distance = abs((y + height / 2.0) - prefer_center)
        rank = (height, -distance)
        if best is None or rank > best[0]:
            best = (rank, y, height)
    return None if best is None else (best[1], best[2])


def _fitted_width(room: float, card_w: float, min_w: float) -> float | None:
    if room < min_w:
        return None
    return min(card_w, room)


def _place_between(
    usable: Rect,
    holes: tuple[Rect, ...],
    card_w: float,
    card_h: float,
    gap: float,
    *,
    min_w: float,
    min_h: float,
) -> Rect | None:
    """Sit the card in a gap between holes when the holes occupy both sides.

    Smaller holes inside that gap only block their own vertical band, so the
    card can sit above or below them. The card narrows to the gap when the
    preferred width does not fit, as long as the explanation still has room.
    """
    if min_h > usable.h or min_w > usable.w or len(holes) < 2:
        return None
    tall = sorted(holes, key=lambda hole: hole.h, reverse=True)[:2]
    left_hole, right_hole = sorted(tall, key=lambda hole: hole.x)
    gap_left = left_hole.right() + gap
    gap_right = right_hole.x - gap
    width = _fitted_width(gap_right - gap_left, card_w, min_w)
    if width is not None:
        x = gap_left + (gap_right - gap_left - width) / 2.0
        prefer = ((left_hole.y + left_hole.h / 2.0) + (right_hole.y + right_hole.h / 2.0)) / 2.0
        slot = _vertical_slot(usable, holes, x, width, gap, prefer, min_h, card_h)
        if slot is not None:
            y, height = slot
            card = Rect(x, y, width, height)
            if _contains(usable, card) and not any(_intersects(card, hole) for hole in holes):
                return card
    spans: list[tuple[float, float]] = []
    left = usable.x
    for item in sorted(holes, key=lambda hole: (hole.x, hole.y)):
        right = item.x - gap
        if right - left >= min_w:
            spans.append((left, right))
        left = max(left, item.right() + gap)
    if usable.right() - left >= min_w:
        spans.append((left, usable.right()))
    if not spans:
        return None
    span_left, span_right = max(spans, key=lambda span: span[1] - span[0])
    width = _fitted_width(span_right - span_left, card_w, min_w)
    if width is None:
        return None
    x = span_left + (span_right - span_left - width) / 2.0
    y_mid = sum(item.y + item.h / 2.0 for item in holes) / len(holes)
    slot = _vertical_slot(usable, holes, x, width, gap, y_mid, min_h, card_h)
    if slot is None:
        return None
    y, height = slot
    card = Rect(x, y, width, height)
    if not _contains(usable, card) or any(_intersects(card, item) for item in holes):
        return None
    return card


def _place_beside(
    usable: Rect,
    hole: Rect,
    card_w: float,
    card_h: float,
    gap: float,
    *,
    min_w: float,
) -> Rect | None:
    """Put the card on the wider side of the hole, narrowing it if needed."""
    if card_h > usable.h:
        return None
    y = hole.top() - card_h
    y = min(max(y, usable.y), usable.top() - card_h)
    candidates: list[Rect] = []
    right_room = usable.right() - hole.right() - gap
    left_room = hole.x - gap - usable.x
    right_w = _fitted_width(right_room, card_w, min_w)
    left_w = _fitted_width(left_room, card_w, min_w)
    if right_w is not None:
        candidates.append(Rect(hole.right() + gap, y, right_w, card_h))
    if left_w is not None:
        candidates.append(Rect(hole.x - gap - left_w, y, left_w, card_h))
    fitting = [cand for cand in candidates if _contains(usable, cand) and not _intersects(cand, hole)]
    if not fitting:
        return None
    return max(fitting, key=lambda cand: cand.w)


def _separate(card: Rect, hole: Rect, usable: Rect, gap: float) -> Rect:
    if not _intersects(card, hole):
        return card
    if card.y < hole.y:
        height = hole.y - gap - card.y
        if height > 0:
            return Rect(card.x, card.y, card.w, min(card.h, height))
    new_y = hole.top() + gap
    height = min(card.h, usable.top() - new_y)
    if height > 0 and new_y >= usable.y:
        return Rect(card.x, new_y, card.w, height)
    return card


def _readable_band_height(band: float, cap: float, floor: float) -> float:
    """How tall a docked card should be in a free band of ``band``.

    A band shorter than ``floor`` still gets ``floor``, so the explanation is
    not crushed into the title row. That card overlaps the spotlight.
    """
    if band >= cap:
        return cap
    if band >= floor:
        return band
    return floor


def place_card(
    *,
    window_width: float,
    window_height: float,
    safe: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
    target: Rect | None = None,
    holes: tuple[Rect, ...] | None = None,
    preferred_size: tuple[float, float] = PREFERRED_CARD,
    min_size: tuple[float, float] = (180.0, 140.0),
    margin: float = MARGIN,
    gap: float = GAP,
    compact_width: float = COMPACT_WIDTH,
    short_height: float = SHORT_HEIGHT,
    min_hole: float = MIN_HOLE,
) -> Placement:
    """Put the card beside the hole, between side-by-side holes, or dock it.

    The card stays inside the safe area. It keeps at least ``min_size`` when
    the window can hold that, so the explanation is not clipped away. A narrow
    window docks full width. A short window still sits beside the hole when
    that gap is wide enough: density scaling can mark a normal window short
    and would otherwise crush the card into the bottom band.
    ``target`` None centers a welcome card and leaves the hole empty.
    ``holes`` are the individual spotlight rects.
    """
    usable = _usable(window_width, window_height, safe, margin)
    pref_w, pref_h = preferred_size
    if target is None:
        card_w = usable.w if window_width < compact_width else min(pref_w, usable.w)
        card_h = min(pref_h, usable.h)
        card = Rect(
            usable.x + max(0.0, (usable.w - card_w) / 2.0),
            usable.y + max(0.0, (usable.h - card_h) / 2.0),
            card_w,
            card_h,
        )
        return _pack(card, None, docked=window_width < compact_width, preferred_h=pref_h)

    hole = spotlight_hole(target, window_width=window_width, window_height=window_height, min_size=min_hole)
    card_w = min(pref_w, usable.w)
    card_h = min(pref_h, usable.h)
    min_w = min(min_size[0], card_w, usable.w)
    min_h = min(min_size[1], card_h, usable.h)
    # ``short_height`` is accepted for callers. A short window still tries to
    # sit beside the hole: density scaling makes that threshold larger than a
    # normal window, and skipping side placement crushed the card.
    narrow = window_width < compact_width
    if not narrow:
        beside = _place_beside(usable, hole, card_w, card_h, gap, min_w=min_w)
        if beside is not None:
            return _pack(beside, hole, docked=False, preferred_h=pref_h)
        if holes:
            between = _place_between(usable, holes, card_w, card_h, gap, min_w=min_w, min_h=min_h)
            if between is not None:
                return _pack(between, hole, docked=False, preferred_h=pref_h)

    below = max(0.0, hole.y - usable.y - gap)
    above = max(0.0, usable.top() - hole.top() - gap)
    floor = min_h
    cap = max(min(pref_h, usable.h), floor)
    # A wide hole has no side to sit on. Keep the preferred width and rest the
    # card against the hole, on the side with more room. A narrow window still
    # uses the full width.
    dock_w = usable.w if narrow else min(card_w, usable.w)
    dock_x = usable.x if narrow else min(max(hole.x, usable.x), usable.right() - dock_w)
    if below >= above:
        height = _readable_band_height(below, cap, floor)
        dock_y = hole.y - gap - height
        if dock_y < usable.y:
            dock_y = usable.y
    else:
        height = _readable_band_height(above, cap, floor)
        dock_y = hole.top() + gap
        if dock_y + height > usable.top():
            dock_y = usable.top() - height
        if dock_y < usable.y:
            dock_y = usable.y
    card = Rect(dock_x, dock_y, dock_w, height)
    card = _clamp(card, usable)
    if card.h + 0.5 >= floor and not _intersects(card, hole):
        card = _separate(card, hole, usable, gap)
        card = _clamp(card, usable)
    return _pack(card, hole, docked=True, preferred_h=pref_h)
