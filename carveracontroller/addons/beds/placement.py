"""MCS placement helpers for beds (pure functions, no Kivy)."""

from __future__ import annotations

import math


def default_origin_xy(anchor1_x: float, anchor1_y: float, anchor_width: float) -> tuple[float, float]:
    """MCS of the front-left top corner from Anchor 1 and L-anchor thickness."""
    return (float(anchor1_x) - float(anchor_width), float(anchor1_y) - float(anchor_width))


def mcs_to_wcs(
    mcs_x: float,
    mcs_y: float,
    mcs_z: float,
    wcox: float,
    wcoy: float,
    wcoz: float,
    rotation_angle_deg: float,
) -> tuple[float, float, float]:
    """Transform a machine-coordinate point into G-code WCS, including XY rotation."""
    theta = math.radians(float(rotation_angle_deg))
    dx = float(mcs_x) - float(wcox)
    dy = float(mcs_y) - float(wcoy)
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    wx = cos_t * dx + sin_t * dy
    wy = -sin_t * dx + cos_t * dy
    wz = float(mcs_z) - float(wcoz)
    return (wx, wy, wz)


def wcs_rotation_4x4(rotation_angle_deg: float) -> tuple[float, ...]:
    """Column-major 4x4 applying MCS→WCS XY rotation from ``rotation_angle`` (OpenGL layout).

    Matches :func:`mcs_to_wcs`::

        wx =  cosθ·dx + sinθ·dy
        wy = -sinθ·dx + cosθ·dy
    """
    theta = math.radians(float(rotation_angle_deg))
    cos_t = math.cos(theta)
    sin_t = math.sin(theta)
    return (
        cos_t,
        -sin_t,
        0.0,
        0.0,
        sin_t,
        cos_t,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        0.0,
        1.0,
    )


def model_offset_viewer(
    mcs_xyz: tuple[float, float, float],
    wcs_origin: tuple[float, float, float],
    scale: float,
) -> tuple[float, float, float]:
    """Scaled MCS−WCS translation applied before the WCS ``rotation_mat``."""
    s = float(scale)
    return (
        (float(mcs_xyz[0]) - float(wcs_origin[0])) * s,
        (float(mcs_xyz[1]) - float(wcs_origin[1])) * s,
        (float(mcs_xyz[2]) - float(wcs_origin[2])) * s,
    )
