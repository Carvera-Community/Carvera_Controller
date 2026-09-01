"""MCS→WCS placement for beds."""

from carveracontroller.addons.beds.placement import (
    default_origin_xy,
    mcs_to_wcs,
    model_offset_viewer,
    wcs_rotation_4x4,
)


def test_default_origin_xy_subtracts_anchor_width():
    x, y = default_origin_xy(-360.158, -234.568, 15.0)
    assert abs(x - (-375.158)) < 1e-9
    assert abs(y - (-249.568)) < 1e-9


def test_mcs_to_wcs_identity_when_unrotated():
    wx, wy, wz = mcs_to_wcs(
        mcs_x=-375.0,
        mcs_y=-250.0,
        mcs_z=5.0,
        wcox=-100.0,
        wcoy=-50.0,
        wcoz=1.0,
        rotation_angle_deg=0.0,
    )
    assert abs(wx - (-275.0)) < 1e-9
    assert abs(wy - (-200.0)) < 1e-9
    assert abs(wz - 4.0) < 1e-9


def test_mcs_to_wcs_rotates_90_degrees():
    wx, wy, wz = mcs_to_wcs(10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 90.0)
    assert abs(wx - 0.0) < 1e-9
    assert abs(wy - (-10.0)) < 1e-9
    assert abs(wz - 0.0) < 1e-9


def test_wcs_rotation_matrix_matches_mcs_to_wcs():
    dx, dy, dz = 12.0, -8.0, 3.0
    angle = 90.0
    wx, wy, wz = mcs_to_wcs(dx, dy, dz, 0.0, 0.0, 0.0, angle)
    m = wcs_rotation_4x4(angle)
    rx = m[0] * dx + m[4] * dy + m[8] * dz + m[12]
    ry = m[1] * dx + m[5] * dy + m[9] * dz + m[13]
    rz = m[2] * dx + m[6] * dy + m[10] * dz + m[14]
    assert abs(rx - wx) < 1e-9
    assert abs(ry - wy) < 1e-9
    assert abs(rz - wz) < 1e-9


def test_model_offset_scales_mcs_minus_wcs():
    offset = model_offset_viewer((-375.0, -250.0, 5.0), (-100.0, -50.0, 1.0), 0.5)
    assert offset == ((-375.0 + 100.0) * 0.5, (-250.0 + 50.0) * 0.5, (5.0 - 1.0) * 0.5)
