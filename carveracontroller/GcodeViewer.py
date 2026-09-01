from __future__ import annotations

import logging
import os
import sys
import threading
from math import *
from typing import Any

from kivy.app import App
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window
from kivy.graphics import *
from kivy.graphics import Callback, Mesh
from kivy.graphics.instructions import RenderContext
from kivy.graphics.opengl import *
from kivy.graphics.texture import Texture
from kivy.graphics.transformation import Matrix
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.widget import Widget
from kivy.utils import platform

from carveracontroller.translation import tr

from .CNC import LASER_TOOL_NUMBER, ZPROBE_TOOL_NUMBER, is_probe_tools_range

logger = logging.getLogger(__name__)

import datetime

start_time = 0


def get_elapsed(str):
    global start_time
    if str == "start":
        start_time = datetime.datetime.now()
    end_time = datetime.datetime.now()
    elapsed_time = (end_time - start_time).total_seconds()
    start_time = end_time
    print(f"{str} -> {elapsed_time}")


# arc camera
import math

from kivy.input.factory import MotionEventFactory
from kivy.input.motionevent import MotionEvent

# input
from kivy.input.provider import MotionEventProvider

from .addons.beds.materials import normalize_bed_material, style_for_bed_material
from .addons.beds.mesh_loader import BED_VERTEX_FORMAT, BedMeshData, load_bed_mesh, pack_bed_mesh_chunks
from .addons.beds.placement import model_offset_viewer, wcs_rotation_4x4
from .addons.stock.simulator import (
    DEFAULT_MESH_THROTTLE_S,
    PLAY_MESH_THROTTLE_S,
    StockSimulator,
)
from .addons.stock.simulator.carver_select import DEFAULT_CARVER_MODE, normalize_carver_mode
from .addons.stock.simulator.mesh_format import VERTEX_FORMAT as CARVED_VERTEX_FORMAT
from .addons.stock.simulator.simulation_quality import (
    CHECKPOINT_SLOTS_BY_LEVEL,
    DEFAULT_CHECKPOINT_LEVEL,
    DEFAULT_VOXEL_RESOLUTION,
    format_cell_size_mm,
    format_diameter_mm,
    normalize_checkpoint_level,
    normalize_voxel_resolution,
)
from .addons.stock.stock_aabb_mesh import (
    STOCK_VERTEX_FORMAT,
    build_box_edges,
    build_box_triangles,
    build_cylinder_edges,
    build_cylinder_triangles,
    build_x_cylinder_edges,
    build_x_cylinder_triangles,
)
from .addons.stock.stock_defaults import default_bounds, default_shape
from .addons.stock.stock_geometry import StockBounds
from .addons.stock.stock_material import (
    DEFAULT_MATERIAL,
    normalize_stock_material,
    preview_fill_rgba,
    style_for_material,
)
from .addons.stock.stock_shape import CylindricalStock, RectangularStock, RotaryCylindricalStock, StockShape
from .addons.tool_visualization.mesh_builder import build_tool_meshes
from .arcball_from_cpp import *
from .Objloader import ObjFile
from .ui.ViewCube import (
    VERTEX_FORMAT as VIEW_CUBE_VERTEX_FORMAT,
)
from .ui.ViewCube import (
    VIEW_FACE_PRESETS,
    pick_face,
)
from .ui.ViewCube import (
    load_mesh as load_view_cube_mesh,
)


# calculate the 3d distance
def len_3d(pos1, pos2):
    return math.sqrt(
        (pos1[0] - pos2[0]) * (pos1[0] - pos2[0])
        + (pos1[1] - pos2[1]) * (pos1[1] - pos2[1])
        + (pos1[2] - pos2[2]) * (pos1[2] - pos2[2])
    )


def len_2d(pos1, pos2):
    return math.sqrt((pos1[0] - pos2[0]) * (pos1[0] - pos2[0]) + (pos1[1] - pos2[1]) * (pos1[1] - pos2[1]))


def normalize(dir):
    length = len_3d(dir, [0, 0, 0])
    if length < 0.0001:
        print("normalize failed")
        return [1, 0, 0]
    inv_length = 1.0 / length
    return [dir[0] * inv_length, dir[1] * inv_length, dir[2] * inv_length]


def normalize_angle(angle):
    while angle < 0:
        angle += 360
    while angle > 360:
        angle -= 360
    return angle


ZOOMSTEP = 1.1
DEFAULT_ZOOM = 0.65
PROJ_NEAR = 2.0
MIN_ZOOM = 0.1
MAX_ZOOM = 10.0
M_PI = 3.141592653
MESH_LINE_CHUNK = 65500  # Max G-code lines per line_strip mesh (65500 vertices)


# binary search left key
def binary_find_left(array, key):
    length = len(array)
    ans = length
    l = 0
    r = length - 1
    while l <= r:
        mid = (l + r) >> 1
        if array[mid] >= key:
            ans = mid
            r = mid - 1
        else:
            l = mid + 1
    return ans - 1


# rotate point around axis & angle
# https://stackoverflow.com/questions/6721544/circular-rotation-around-an-arbitrary-axis
# https://kivy.org/doc/stable/api-kivy.graphics.transformation.html
def rotate_pt_by_x_axis_angle(pt_x, pt_y, pt_z, angle_in_degree):
    axis = [1, 0, 0]
    mat_rot_x = Matrix()
    angle_in_radian = angle_in_degree * 3.1415926 / 180.0
    mat_rot_x.rotate(angle_in_radian, axis[0], axis[1], axis[2])
    rot_pt = mat_rot_x.transform_point(pt_x, pt_y, pt_z)
    return rot_pt


def rotate_mat_by_x_axis_angle(angle_in_degree):
    axis = [1, 0, 0]
    mat_rot_x = Matrix()
    angle_in_radian = angle_in_degree * 3.1415926 / 180.0
    mat_rot_x.rotate(angle_in_radian, axis[0], axis[1], axis[2])
    return mat_rot_x


#####function
def vec3_add(v1, v2):
    return [v1[0] + v2[0], v1[1] + v2[1], v1[2] + v2[2]]


def vec3_sub(v1, v2):
    return [v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2]]


def vec3_mul_float(v1, f):
    return [v1[0] * f, v1[1] * f, v1[2] * f]


def vec3_divide(v1, ff):
    f = 1.0 / ff
    return [v1[0] * f, v1[1] * f, v1[2] * f]


def vec3_len(v1):
    return sqrt(v1[0] * v1[0] + v1[1] * v1[1] + v1[2] * v1[2])


def vec3_max(v1, v2):
    return [max(v1[0], v2[0]), max(v1[1], v2[1]), max(v1[2], v2[2])]


def vec3_min(v1, v2):
    return [min(v1[0], v2[0]), min(v1[1], v2[1]), min(v1[2], v2[2])]


def bbox_max_side_length(min_pt, max_pt):
    """Retrieve the largest axis span from the bounding box"""
    ex = max_pt[0] - min_pt[0]
    ey = max_pt[1] - min_pt[1]
    ez = max_pt[2] - min_pt[2]
    m = max(ex, ey, ez)
    if m <= 0.0 or not isfinite(m):
        return 0.0
    return m


def vec3_distance(v1, v2):
    v3 = vec3_sub(v1, v2)
    return vec3_len(v3)


GRID_STEP_MM = 10.0
GRID_MAJOR_STEP_MM = 100.0
GRID_COLOR_MINOR = [0.35, 0.35, 0.35]
GRID_COLOR_MAJOR = [0.55, 0.55, 0.55]
# axis.obj points along +Y; rotations map meshes to world axes (see axis arrow setup)
AXIS_COLOR_X = [1.0, 0.0, 0.0]
AXIS_COLOR_Y = [0.0, 1.0, 0.0]
AXIS_COLOR_Z = [0.0, 0.0, 1.0]

# T1–T10 tool colors (matches toolpath.glsl tool_palette_color).
TOOL_PALETTE = (
    (0.406684, 0.735902, 0.235489, 1),
    (0.000000, 0.459774, 0.840728, 1),
    (0.779915, 0.319537, 0.130857, 1),
    (0.740127, 0.236840, 0.700182, 1),
    (0.000000, 0.755849, 0.602221, 1),
    (0.825216, 0.043248, 0.043248, 1),
    (0.894806, 0.717161, 0.000000, 1),
    (0.128923, 0.578319, 0.877916, 1),
    (0.431518, 0.268501, 0.839063, 1),
    (0.248716, 0.777237, 0.402157, 1),
)

DEFAULT_FEED_MM_MIN = 3000.0
DEFAULT_AXIS_LIMITS = {
    "x": 3000.0,
    "y": 3000.0,
    "z": 2000.0,
    "a": 1800.0,
    "seek": DEFAULT_FEED_MM_MIN,
}
MIN_FEED_MM_MIN = 0.001
MOVE_EPS_MM = 1e-5
ROTARY_RADIUS_EPS_MM = 0.1
VERTEX_FLOAT_NUM = 11

# Marks a touch this widget took on touch_down, so drags belonging to the
# controls floating over it are not also treated as orbit or pan.
TOUCH_CLAIMED = "gcode_viewer_claimed"

COLOR_SCHEME_BY_TYPE = 0
COLOR_SCHEME_BY_TOOL = 1
COLOR_SCHEME_BY_SPEED = 2
COLOR_SCHEME_BY_Z = 3
COLOR_SCHEME_UI_BY_TYPE = "Move type"
COLOR_SCHEME_UI_BY_TOOL = "Tool"
COLOR_SCHEME_UI_BY_SPEED = "Speed"
COLOR_SCHEME_UI_BY_Z = "Height"

# Legend / shader bucket counts for speed and height filters.
VISIBILITY_BUCKET_COUNT = 11
VISIBILITY_ALL_BUCKET_BITS = (1 << VISIBILITY_BUCKET_COUNT) - 1

# Max tool ids that we can pass to the shader (6 x vec4).
VISIBILITY_MAX_TOOLS = 24

# Height colormap: range from feed-move Z percentiles (ignores G0 and outlier G1).
Z_HEIGHT_PERCENTILE_LOW = 5.0
Z_HEIGHT_PERCENTILE_HIGH = 95.0


def feed_mm_min_for_move(is_rapid, feed_value=None):
    """Feed rate (mm/min) stored per vertex; 0 for rapid moves."""
    if is_rapid:
        return 0.0
    if feed_value is not None:
        try:
            feed = float(feed_value)
            if feed > 0.0:
                return feed
        except (TypeError, ValueError):
            pass
    return DEFAULT_FEED_MM_MIN


def _percentile_from_sorted(sorted_vals, percentile):
    """Linear-interpolation percentile; percentile in 0..100."""
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_vals[0])
    k = (n - 1) * (float(percentile) / 100.0)
    f = int(k)
    c = min(f + 1, n - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]))


def _feed_z_height_range_mm(
    positions,
    raw_feed_rates,
    low_pct=Z_HEIGHT_PERCENTILE_LOW,
    high_pct=Z_HEIGHT_PERCENTILE_HIGH,
):
    """Z range (mm) for height coloring: percentiles of feed-move vertices only."""
    if not positions or len(positions) < 3:
        return 0.0, 1.0

    feeds = raw_feed_rates or []
    vertex_count = len(positions) // 3
    zs = []
    for i in range(vertex_count):
        if i < len(feeds) and float(feeds[i]) > 0.0:
            zs.append(float(positions[3 * i + 2]))

    if not zs:
        zs = [float(positions[i]) for i in range(2, len(positions), 3)]
    if not zs:
        return 0.0, 1.0

    zs.sort()
    z_min = _percentile_from_sorted(zs, low_pct)
    z_max = _percentile_from_sorted(zs, high_pct)
    if z_max <= z_min:
        z_min = zs[0]
        z_max = zs[-1]
    if z_max <= z_min:
        z_max = z_min + 1.0
    return z_min, z_max


def tool_palette_rgb(tool_number):
    """RGB from tool number, wrapping through TOOL_PALETTE (matches toolpath.glsl)."""
    idx = (int(tool_number) - 1) % len(TOOL_PALETTE)
    return TOOL_PALETTE[idx][:3]


def tool_marker_palette_rgb(tool_number):
    """Pastel RGB for progress-bar tool labels, derived from tool_palette_rgb."""
    r, g, b = tool_palette_rgb(tool_number)
    t = 0.4
    return (r * (1 - t) + t, g * (1 - t) + t, b * (1 - t) + t)


def speed_colormap_rgb(t):
    """Match toolpath.glsl speed_colormap."""
    t = max(0.0, min(1.0, float(t)))
    if t < 0.33:
        a = (0.2, 0.4, 0.9)
        b = (0.1, 0.7, 0.5)
        u = t / 0.33
    elif t < 0.66:
        a = (0.1, 0.7, 0.5)
        b = (0.95, 0.85, 0.15)
        u = (t - 0.33) / 0.33
    else:
        a = (0.95, 0.85, 0.15)
        b = (0.9, 0.25, 0.2)
        u = (t - 0.66) / 0.34
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u)


GRID_QUAD_MIN_SIZE = 10.0
CONFIG_GRID_VISIBLE_KEY = "gcode_viewer_show_grid"
VIEW_CUBE_SIZE = dp(96)
VIEW_CUBE_MARGIN = dp(10)
VIEW_CUBE_TOOLBAR_INSET = dp(48)
VIEW_CUBE_TEXTURE_UNIT = 1
VIEW_CUBE_WORLD_SCALE = 0.5
LASER_DECAL_TEXTURE_UNIT = 1


# Assets (3D models / textures)
def _gcode_viewer_asset(name):
    return os.path.join(os.path.dirname(__file__), "data", "GcodeViewer", name)


VIEW_CUBE_ATLAS_PATH = _gcode_viewer_asset("view_cube_atlas.png")
VIEW_CUBE_MODEL_PATH = _gcode_viewer_asset("view_cube_model.obj")
AXIS_OBJ_PATH = _gcode_viewer_asset("axis.obj")


class MeshManager:
    def __init__(self):
        ##data container

        self.positions = []
        # raw positions (unrotated G-code coordinates)
        self.raw_positions = []
        # all lengths
        self.lengths = []
        # vertex type
        self.vertex_types = []
        # raw numbers
        self.raw_linenumbers = []
        # feed rate (mm/min) per vertex, from CNC parser
        self.raw_feed_rates = []
        # spindle RPM / laser S (0–1 PWM fraction in laser mode) per vertex
        self.raw_spindle_speeds = []
        # active tool number per vertex, used to pick the tool mesh to display
        self.raw_tools = []
        # angles of vertices [4 axis]
        self.angles_of_vertices = []

        # mesh container
        self.meshes = []

        # vertices
        self.vertices = []
        ##  bounding area

        # record the max size of area
        self.area_size = 0.0
        # bounding box (min/max per axis)
        self.min_pt = [float("inf"), float("inf"), float("inf")]
        self.max_pt = [float("-inf"), float("-inf"), float("-inf")]
        # cetner of meshes
        self.area_center_sum = [0, 0, 0]
        self.area_center_sum_index = 0
        self.position_scale = 1.0  # same to scale_invert

        ## attributes
        self.is_4_axis = None

    def clear(self):
        self.positions.clear()
        self.raw_positions.clear()
        # all lengths
        self.lengths.clear()
        # vertex type
        self.vertex_types.clear()
        # raw numbers
        self.raw_linenumbers.clear()
        self.raw_feed_rates.clear()
        self.raw_spindle_speeds.clear()
        self.raw_tools.clear()
        # angles of vertices [4 axis]
        self.angles_of_vertices.clear()
        # mesh container
        self.meshes.clear()
        # vertices
        self.vertices.clear()

        # move to origin
        self.area_size = 0.0
        self.min_pt = [float("inf"), float("inf"), float("inf")]
        self.max_pt = [float("-inf"), float("-inf"), float("-inf")]
        self.area_center_sum = [0, 0, 0]
        self.area_center_sum_index = 0
        self.position_scale = 1.0  # same to scale_invert
        self.is_4_axis = None

    def get_pt_count(self):
        return len(self.positions)

    # get center of meshes
    def get_center(self):
        if self.area_center_sum_index == 0:
            return [0, 0, 0]

        return vec3_divide(self.area_center_sum, self.area_center_sum_index)

    def get_center_of_view(self):
        return vec3_mul_float(self.get_center(), self.position_scale)

    def get_vertex_position(self, idx):
        base = idx * VERTEX_FLOAT_NUM
        return [self.vertices[base], self.vertices[base + 1], self.vertices[base + 2]]

    def parse_line_data(self, linedata):
        # position (raw G-code coordinates)
        raw_pos = [linedata[0], linedata[1], linedata[2]]

        # Store raw positions before rotation
        self.raw_positions.extend(raw_pos)

        # angle
        angle = linedata[3]
        pos = rotate_pt_by_x_axis_angle(raw_pos[0], raw_pos[1], raw_pos[2], angle)

        self.positions.extend(pos)
        self.min_pt = vec3_min(self.min_pt, pos)
        self.max_pt = vec3_max(self.max_pt, pos)

        # for center calculating
        self.area_center_sum = vec3_add(self.area_center_sum, pos)
        self.area_center_sum_index += 1

        # get attributes of this point
        vertex = [0] * VERTEX_FLOAT_NUM
        # 1 position
        vertex[0] = pos[0]
        vertex[1] = pos[1]
        vertex[2] = pos[2]

        # angle

        # 2 color
        color = [1.0, 0.0, 0.0] if linedata[4] == 0.0 else [0.0, 1.0, 0.0]
        vertex[3] = color[0]
        vertex[4] = color[1]
        vertex[5] = color[2]

        # 3 line number in gcode
        vertex[6] = linedata[5]

        # 4 type id
        vertex[7] = len(self.positions) - 1

        # 5 distance attribute
        vertex[8] = 0  # set after length is calculated

        # 6 set tool knife id
        vertex[9] = linedata[6]

        # 7 feed rate (mm/min)
        is_rapid = linedata[4] == 0.0 or linedata[4] < 0.5
        feed_value = linedata[7] if len(linedata) > 7 else None
        feed = feed_mm_min_for_move(is_rapid, feed_value)
        vertex[10] = feed

        # push this vertex to container
        self.vertices.extend(vertex)
        self.vertex_types.append(1.0 if linedata[4] > 0.5 else 2.0)  # line type[red | green]
        self.raw_linenumbers.append(vertex[6])
        self.raw_feed_rates.append(feed)
        speed = float(linedata[8]) if len(linedata) > 8 else 0.0
        self.raw_spindle_speeds.append(speed)
        self.raw_tools.append(vertex[9])
        self.angles_of_vertices.append(angle)

    def generate_meshes(self):
        # 0 scale all points to fit largest bbox side in ~2 units
        vertex_count = len(self.positions) // 3
        vertex_float_num = VERTEX_FLOAT_NUM
        if vertex_count == 0:
            self.meshes.clear()
            return
        max_extent = bbox_max_side_length(self.min_pt, self.max_pt)
        self.position_scale = (2.0) if max_extent == 0 else (2.0 / max_extent)
        for i in range(vertex_count):
            self.vertices[vertex_float_num * i + 0] = self.positions[3 * i + 0] * self.position_scale
            self.vertices[vertex_float_num * i + 1] = self.positions[3 * i + 1] * self.position_scale
            self.vertices[vertex_float_num * i + 2] = self.positions[3 * i + 2] * self.position_scale

        # 1 calculate lengths
        self.lengths = [0] * vertex_count
        for i in range(1, vertex_count):
            pos1 = [
                self.vertices[vertex_float_num * (i - 1) + 0],
                self.vertices[vertex_float_num * (i - 1) + 1],
                self.vertices[vertex_float_num * (i - 1) + 2],
            ]
            pos2 = [
                self.vertices[vertex_float_num * (i) + 0],
                self.vertices[vertex_float_num * (i) + 1],
                self.vertices[vertex_float_num * (i) + 2],
            ]

            cur_line_len = vec3_distance(pos1, pos2)
            self.lengths[i] = self.lengths[i - 1] + cur_line_len

        # 2 set distance id
        for i in range(vertex_count):
            self.vertices[vertex_float_num * i + 8] = self.lengths[i]

        self.seg_mesh_vertex_count = MESH_LINE_CHUNK

        # 3 construct meshes
        self.meshes.clear()
        mesh_start_id = 0
        mesh_end_id = min(self.seg_mesh_vertex_count, vertex_count)  # not included

        while True:
            # process each mesh
            indices = []
            for i in range(mesh_end_id - mesh_start_id):
                indices.append(i)
            mesh = [self.vertices[vertex_float_num * mesh_start_id : vertex_float_num * mesh_end_id], indices]

            self.meshes.append(mesh)

            # skip to next mesh
            if mesh_end_id == vertex_count:
                break  # run to end

            # resuse the last mesh vertex to make sure continous lines
            mesh_start_id = mesh_end_id - 1
            mesh_end_id = min(mesh_start_id + self.seg_mesh_vertex_count, vertex_count)

    def add_data_arrs(self, rawdata, is_end=True):
        # parse line

        # 1 check gcode type
        self.is_4_axis = True

        # 2 parse single line
        for linedata in rawdata:
            self.parse_line_data(linedata)

        if is_end:
            self.generate_meshes()


def frame_call_back_test(distance, num):
    print(f"Current line: {num}")


class GCodeViewer(Widget):
    axis = (0, 0, 1)
    angle = 0

    three_axis_mode = True

    g_old_curosr = [0, 0]
    g_cursor = [0, 0]
    left_button_down = False
    middle_button_down = False
    right_button_down = False
    g_wheel_data = 0
    lines_center = [0, 0, 0]

    display_count = 0
    total_line_count = 0
    add_dir = 1
    dynamic_display = BooleanProperty(True)
    move_speed = 0.8
    move_scale = 1.0
    move_scale_by_positon = 1.0

    # Clear cached mesh data before loading a new file
    clear_before_new_load = False

    # When True, compute segment-based time estimates (distance/feed); when False, skip extra parsing.
    high_precision_time_estimate = True

    # Cut-simulation stats (progress, checkpoints, HUD texts)
    sim_progress = NumericProperty(0.0)
    sim_checkpoints = ListProperty([])
    sim_hud_text = StringProperty("")
    stock_visible = BooleanProperty(False)
    bed_visible = BooleanProperty(False)

    line_times = []
    line_times_job_id = 0
    line_times_job_show_progress = False
    total_time = 0.0
    legend_durations_cache = None
    lengths = []
    raw_linenumbers = []
    raw_positions = []
    raw_feed_rates = []
    raw_spindle_speeds = []
    raw_tools = []
    angles_of_vertices = []
    frame_callback = None

    # Tool number -> ToolDefinition extracted from the loaded file's CAM comments.
    # Set from outside (see main.py) before/at the final load_array() call.
    tool_table = {}
    # Multiplier converting tool-comment dimensions (file units) into the same
    # millimetre space as parsed coordinates (1.0 for mm files, 25.4 for inch).
    tool_unit_scale = 1.0
    time_estimate_progress_callback = None
    log_callback = None
    error_popup_callback = None

    # camera
    m_xRot = 30
    m_yRot = 180

    m_xRotTarget = 90
    m_yRotTarget = 0

    m_zoom = DEFAULT_ZOOM

    m_xPan = 0
    m_yPan = 0
    m_xLastRot = 30
    m_yLastRot = 180
    m_xLastPan = 0
    m_yLastPan = 0
    m_lastPos = [0, 0]
    m_distance = 10

    m_xLookAt = 0
    m_yLookAt = 0
    m_zLookAt = 0

    m_xMin = 0
    m_xMax = 0
    m_yMin = 0
    m_yMax = 0
    m_zMin = 0
    m_zMax = 0
    m_xSize = 0
    m_ySize = 0
    m_zSize = 0

    off_x = 0
    off_y = 0

    orbit = True
    _grid_visible = True
    _ortho_projection = False
    color_scheme = COLOR_SCHEME_BY_TOOL
    feed_min = 0.0
    feed_max = DEFAULT_FEED_MM_MIN
    z_min = 0.0
    z_max = 1.0
    z_min_mm = 0.0
    z_max_mm = 1.0

    def __init__(self) -> None:
        super().__init__()
        self.canvas = RenderContext()
        shader_dir = os.path.join(os.path.dirname(__file__), "shaders")

        self.gridmesh = RenderContext()
        self.gridmesh.shader.source = os.path.join(shader_dir, "grid.glsl")
        self._setup_grid_quad()

        self.linemesh = RenderContext()
        self.linemesh.shader.source = os.path.join(shader_dir, "toolpath.glsl")

        self.stockmesh = RenderContext()
        self.stockmesh.shader.source = os.path.join(shader_dir, "stock.glsl")

        self.bedmesh = RenderContext()
        self.bedmesh.shader.source = os.path.join(shader_dir, "bed.glsl")
        self.bedmesh["metallic"] = 0.0
        self.bedmesh["roughness"] = 0.85
        self.bedmesh["model_offset"] = (0.0, 0.0, 0.0)
        self.bed_visible = False
        self._bed_mesh_path: str | None = None
        self._bed_mcs_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._bed_material = "mdf"
        self._bed_loaded: BedMeshData | None = None
        self._bed_thickness_mm = 0.0
        self._bed_wcs_applied: tuple[float, float, float, float] | None = None

        self.carvedmesh = RenderContext()
        self.carvedmesh.shader.source = os.path.join(shader_dir, "carved_stock.glsl")
        self.carvedmesh["vertex_scale"] = 1.0
        self.carvedmesh["laser_enabled"] = 0.0
        self.carvedmesh["laser_mode"] = 0.0
        self.carvedmesh["use_two_tone"] = 0.0
        self.carvedmesh["use_height_tint"] = 1.0
        self.carvedmesh["cylindrical_skin"] = 0.0
        self.carvedmesh["metallic"] = 0.0
        self.carvedmesh["interior_metallic"] = 0.0
        self.carvedmesh["roughness"] = 0.92
        self.carvedmesh["interior_roughness"] = 0.92
        self.carvedmesh["texture1"] = LASER_DECAL_TEXTURE_UNIT
        self._carved_meshes: dict[tuple[int, int, int], Mesh] = {}
        self._carved_mesh_anchor = None
        self._laser_texture = None
        self._laser_mode = "planar"
        with self.carvedmesh:
            Callback(self.setup_gl_context)
            Callback(self._setup_carved_gl)
            self._carved_mesh_anchor = Callback(None)
            Callback(self._reset_carved_gl)
            Callback(self.reset_gl_context)

        self.pointermesh = RenderContext()
        self.pointermesh.shader.source = os.path.join(shader_dir, "tool_pointer.glsl")

        axis_shader = os.path.join(shader_dir, "axis_helper.glsl")
        self.axisxmesh = RenderContext()
        self.axisxmesh.shader.source = axis_shader
        self.axisymesh = RenderContext()
        self.axisymesh.shader.source = axis_shader
        self.axiszmesh = RenderContext()
        self.axiszmesh.shader.source = axis_shader

        self.viewcubemesh = RenderContext()
        self.viewcubemesh.shader.source = os.path.join(shader_dir, "view_cube.glsl")
        self._setup_view_cube_mesh()

        self.meshmanager = MeshManager()
        self.positions = []

        # Per-tool generated meshes (tool number -> (vertices, indices, vertex_format)),
        # rebuilt whenever a new file finishes loading. `pointer_mesh_instrs` holds the
        # back-face then front-face Mesh pair whose geometry is swapped on tool change.
        self._tool_meshes = {}
        self._default_tool_mesh = None
        self.pointer_mesh_instrs = []
        self._active_tool_number = None

        # Dirty flags: set True whenever the scene must be re-rendered.
        # _scene_dirty covers view/pointer/axis uniform changes; _proj_dirty
        # covers the projection matrix (zoom, pan, resize).
        self._scene_dirty = True
        self._proj_dirty = True

        # Pre-computed constant matrices reused every frame to avoid per-frame
        self._identity_mat = Matrix()
        self._stock_rotation_mat = self._identity_mat
        self._axis_y_rot = Matrix().rotate(0.5 * math.pi, 1, 0, 0)
        self._axis_z_rot = Matrix().rotate(-0.5 * math.pi, 0, 0, 1)
        self._proj_matrix = Matrix()
        self.m_viewMatrix = Matrix()
        self._grid_visible = Config.getboolean("carvera", CONFIG_GRID_VISIBLE_KEY, fallback=True)
        self._viewer_meshes_active = False

        self.viewcubemesh["texture0"] = VIEW_CUBE_TEXTURE_UNIT
        self._view_cube_proj = Matrix()

        self.bind(size=self._on_size_change, pos=self._on_size_change)

        self.show_rapid = True
        self.show_feed = True
        self.speed_bucket_bits = VISIBILITY_ALL_BUCKET_BITS
        self.z_bucket_bits = VISIBILITY_ALL_BUCKET_BITS
        self._tool_filter_ids = []
        self._tool_filter_bits = 0

        self._apply_color_scheme_uniform()
        self._update_feed_range_uniforms()
        self._apply_visibility_uniforms()

        # Stock preview / cut simulation state
        self.stock_bounds_mm: StockBounds | None = None
        self.stock_shape: StockShape | None = None
        self.stock_visible = False
        self.simulate_cut = False
        self.stock_mesh_while_playing = False
        # Keep the translucent AABB up after pause until the worker flush
        # patches GPU chunks; otherwise the last meshed shell (often uncut)
        # is shown for a frame.
        self._defer_carved_stock = False
        self.stock_voxel_resolution = DEFAULT_VOXEL_RESOLUTION
        self.stock_checkpoint_level = DEFAULT_CHECKPOINT_LEVEL
        self.stock_carver_mode = DEFAULT_CARVER_MODE
        self.stock_material = DEFAULT_MATERIAL
        self._sim_carved_vertex = 0
        self._sim_progress_vertex = 0
        self._sim_progress_trigger = Clock.create_trigger(self._flush_sim_progress, 0)
        self._sim_checkpoints_trigger = Clock.create_trigger(self._flush_sim_checkpoints, 0)
        self._pending_checkpoint_vertices: list[int] = []
        self._stock_simulator = StockSimulator(
            on_meshes_ready=self._on_stock_meshes_ready,
            on_progress=self._on_stock_progress,
            on_checkpoints=self._on_stock_checkpoints,
        )
        self.bind(dynamic_display=self._on_dynamic_display_changed)

        # HUD lives in float_layout — this RenderContext cannot host 2D Labels.
        self._sim_hud_trigger = Clock.create_trigger(self._refresh_sim_hud, 0)

        self._apply_default_stock_settings()

        Clock.schedule_interval(self._on_frame_tick, 1 / 60)

    def _on_size_change(self, *args):
        self._proj_dirty = True
        self._scene_dirty = True

    def _view_cube_hud_proj(self):
        """Square ortho projection for the HUD viewport (independent of zoom/pan)."""
        proj = Matrix()
        proj.view_clip(-1.0, 1.0, -1.0, 1.0, 0.1, self.m_distance * 4.0, 0)
        return proj

    def _view_cube_active(self):
        return self._viewer_meshes_active

    def _update_view_cube_uniforms(self):
        if not self._view_cube_active():
            return
        self._view_cube_proj = self._view_cube_hud_proj()
        self.viewcubemesh["view_mat"] = self.m_viewMatrix
        self.viewcubemesh["proj_mat"] = self._view_cube_proj
        self.viewcubemesh["cube_scale"] = float(VIEW_CUBE_WORLD_SCALE)

    def _setup_view_cube_mesh(self):
        verts, indices = load_view_cube_mesh(VIEW_CUBE_MODEL_PATH)
        self.viewcubemesh.clear()
        with self.viewcubemesh:
            self._view_cube_cb_setup = Callback(self._setup_view_cube_gl)
            BindTexture(source=VIEW_CUBE_ATLAS_PATH, index=VIEW_CUBE_TEXTURE_UNIT)
            Mesh(
                fmt=VIEW_CUBE_VERTEX_FORMAT,
                vertices=verts,
                indices=indices,
                mode="triangles",
            )
            self._view_cube_cb_reset = Callback(self._reset_view_cube_gl)

    def _view_cube_gl_origin(self):
        """Bottom-left of the GL drawable area (same origin as setup_gl_context)."""
        return self.pos[0] + self.off_x, self.pos[1] + self.off_y

    def _view_cube_widget_rect(self):
        """Cube HUD bounds relative to the GL drawable area (origin bottom-left)."""
        size = int(VIEW_CUBE_SIZE)
        margin = int(VIEW_CUBE_MARGIN)
        toolbar = int(VIEW_CUBE_TOOLBAR_INSET)
        x = margin
        y = self.size[1] - toolbar - margin - size
        return x, y, size, size

    def _view_cube_screen_rect(self):
        """Cube HUD bounds in window coordinates for glViewport."""
        ox, oy = self._view_cube_gl_origin()
        x, y, size, _ = self._view_cube_widget_rect()
        return int(ox + x), int(oy + y), size, size

    def _view_cube_hit_screen_rect(self):
        """Visible cube bounds — smaller than the HUD viewport (see cube_scale)."""
        wx, wy, w, h = self._view_cube_screen_rect()
        scale = float(VIEW_CUBE_WORLD_SCALE)
        hit_w = w * scale
        hit_h = h * scale
        return wx + (w - hit_w) * 0.5, wy + (h - hit_h) * 0.5, hit_w, hit_h

    def _view_cube_touch_ndc(self, touch):
        """Map a touch to NDC inside the cube HUD, or None if outside."""
        wx, wy, w, h = self._view_cube_screen_rect()
        hit_x, hit_y, hit_w, hit_h = self._view_cube_hit_screen_rect()
        if self.parent is not None:
            touch_wx, touch_wy = self.parent.to_window(touch.pos[0], touch.pos[1])
        else:
            touch_wx, touch_wy = touch.x, touch.y
        if not (hit_x <= touch_wx <= hit_x + hit_w and hit_y <= touch_wy <= hit_y + hit_h):
            return None
        ndc_x = 2.0 * (touch_wx - wx) / w - 1.0
        ndc_y = 2.0 * (touch_wy - wy) / h - 1.0
        return ndc_x, ndc_y

    def _setup_view_cube_gl(self, *args):
        x, y, w, h = self._view_cube_screen_rect()
        glViewport(int(x), int(y), int(w), int(h))
        glEnable(GL_DEPTH_TEST)
        glClear(GL_DEPTH_BUFFER_BIT)
        glActiveTexture(GL_TEXTURE0 + VIEW_CUBE_TEXTURE_UNIT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        self._update_view_cube_uniforms()

    def _reset_view_cube_gl(self, *args):
        glDisable(GL_DEPTH_TEST)
        glViewport(0, 0, int(Window.size[0]), int(Window.size[1]))

    def _handle_view_cube_touch(self, touch):
        if not self._view_cube_active():
            return False
        ndc = self._view_cube_touch_ndc(touch)
        if ndc is None:
            return False
        ndc_x, ndc_y = ndc
        face_id = pick_face(
            ndc_x,
            ndc_y,
            self.m_viewMatrix,
            self._view_cube_hud_proj(),
            VIEW_CUBE_WORLD_SCALE,
        )
        self.m_xRot, self.m_yRot = VIEW_FACE_PRESETS[face_id]
        self.update_view()
        self._scene_dirty = True
        return True

    def _raise_view_cube_to_top(self):
        if self.viewcubemesh in self.canvas.children:
            self.canvas.remove(self.viewcubemesh)
        self.canvas.add(self.viewcubemesh)

    def _remove_view_cube_from_canvas(self):
        if self.viewcubemesh in self.canvas.children:
            self.canvas.remove(self.viewcubemesh)

    def _get_line_vertex_fmt(self):
        return [
            (b"position", 3, "float"),
            (b"color_att", 3, "float"),
            (b"type", 1, "float"),
            (b"vertex_id", 1, "float"),
            (b"distance_id", 1, "float"),
            (b"vertex_tool", 1, "float"),
            (b"vertex_feed", 1, "float"),
        ]

    def _get_grid_vertex_fmt(self):
        return [(b"position", 3, "float")]

    def _setup_grid_quad(self):
        """Single quad on the XY plane; grid lines are drawn in the fragment shader."""
        verts = [-0.5, -0.5, 0.0, 0.5, -0.5, 0.0, -0.5, 0.5, 0.0, 0.5, 0.5, 0.0]
        indices = [0, 1, 2, 2, 1, 3]
        self.gridmesh.clear()
        with self.gridmesh:
            self.cb = Callback(self.setup_gl_context)
            Mesh(
                fmt=self._get_grid_vertex_fmt(),
                vertices=verts,
                indices=indices,
                mode="triangles",
            )
            self.cb = Callback(None)

    def _add_canvas_children(self):
        self.canvas.add(self.gridmesh)
        if self.bed_visible:
            self.canvas.add(self.bedmesh)
        if self.stock_visible or self.simulate_cut:
            self.canvas.add(self.stockmesh)
            self.canvas.add(self.carvedmesh)
        self.canvas.add(self.linemesh)
        self.canvas.add(self.pointermesh)
        self.canvas.add(self.axisxmesh)
        self.canvas.add(self.axisymesh)
        self.canvas.add(self.axiszmesh)
        self._raise_view_cube_to_top()
        self._update_view_cube_uniforms()
        self._viewer_meshes_active = True
        self._update_bed_uniforms()
        self._update_stock_uniforms()
        self._update_carved_uniforms()

    def _grid_quad_extent(self):
        """World-space quad width so the plane covers the viewport when orbiting."""
        asp = self.size[0] / max(self.size[1], 1.0)
        return max(self.m_distance * self.m_zoom * max(asp, 1.0) * 4.0, GRID_QUAD_MIN_SIZE)

    def _update_grid_uniforms(self):
        scale = self.move_scale_by_positon if self.move_scale_by_positon else 1.0
        center = getattr(self, "lines_center", [0.0, 0.0, 0.0])
        self.gridmesh["center_offset"] = Matrix().translate(-center[0], -center[1], -center[2])
        self.gridmesh["view_mat"] = self.m_viewMatrix
        self.gridmesh["grid_visible"] = 1.0 if self._grid_visible else 0.0
        self.gridmesh["grid_size"] = float(self._grid_quad_extent())
        self.gridmesh["subcell_size"] = float(GRID_STEP_MM * scale)
        self.gridmesh["cell_size"] = float(GRID_MAJOR_STEP_MM * scale)
        self.gridmesh["color_minor"] = GRID_COLOR_MINOR
        self.gridmesh["color_major"] = GRID_COLOR_MAJOR
        self.gridmesh["color_axis_x"] = AXIS_COLOR_X
        self.gridmesh["color_axis_y"] = AXIS_COLOR_Y

    def clearDisplay(self, close_progress=True):
        self.lengths = []
        self._cannot_visualise = False
        self.vertex_types = []
        self.positions = []
        self.line_times = []
        self.total_time = 0.0
        self._invalidate_legend_durations()
        self._begin_line_times_job(show_progress=False, close_progress=close_progress)
        self.raw_feed_rates = []
        self.raw_spindle_speeds = []
        self.raw_tools = []
        self._tool_meshes = {}
        self._default_tool_mesh = None
        self.pointer_mesh_instrs = []
        self._active_tool_number = None
        self.linemesh.clear()
        self.canvas.remove(self.linemesh)
        self.canvas.remove(self.gridmesh)
        if self.bedmesh in self.canvas.children:
            self.canvas.remove(self.bedmesh)
        if self.stockmesh in self.canvas.children:
            self.canvas.remove(self.stockmesh)
        if self.carvedmesh in self.canvas.children:
            self.canvas.remove(self.carvedmesh)
        self._clear_carved_meshes()
        self.canvas.remove(self.pointermesh)
        self.pointermesh.clear()
        self.canvas.remove(self.axisxmesh)
        self.axisxmesh.clear()
        self.canvas.remove(self.axisymesh)
        self.axisymesh.clear()
        self.canvas.remove(self.axiszmesh)
        self.axiszmesh.clear()
        self._remove_view_cube_from_canvas()
        self.display_count = 0
        self._sim_carved_vertex = 0
        self._sim_progress_vertex = 0
        self.sim_progress = 0.0
        self.sim_checkpoints = []
        self.sim_hud_text = ""
        self.stock_visible = False
        self.bed_visible = False
        self.simulate_cut = False
        self._defer_carved_stock = False
        self._viewer_meshes_active = False
        self._stock_rotation_mat = self._identity_mat
        if self._stock_simulator is not None:
            # Keep bounds/shape/quality, but pause carving until the new file finishes loading.
            self._stock_simulator.clear_toolpath()
            self._stock_simulator.disable()
        self._sim_hud_trigger()

    def set_frame_callback(self, framecallback):
        self.frame_callback = framecallback

    def set_error_popup_callback(self, callback):
        """Set callback(message) to show error in UI (e.g. load_error popup). Called when gcode cannot be visualised."""
        self.error_popup_callback = callback

    def set_play_over_callback(self, playovercallback):
        self.play_over_callback = playovercallback

    def begin_new_file_load(self):
        """Drop leftover path vertices so a new file cannot inherit the previous load."""
        self.clear_before_new_load = False
        self.meshmanager.clear()
        self.total_distance = 0.0
        self.total_line_count = 0

    def clear_loaded_memery(self):
        if self.clear_before_new_load:
            self.clear_before_new_load = False

            self.meshmanager.clear()

    def _tool_number_at_index(self, vertex_idx):
        """Return the active tool number (int) at a given vertex index, or None."""
        if not self.raw_tools:
            return None
        vertex_idx = max(0, min(vertex_idx, len(self.raw_tools) - 1))
        return int(self.raw_tools[vertex_idx])

    def _get_tool_mesh(self, tool_number):
        """Return the (vertices, indices, vertex_format) mesh for a tool number.

        Falls back to the default (basic pointed) mesh when the tool number
        is unknown or has no metadata in the loaded file.
        """
        if tool_number is not None and tool_number in self._tool_meshes:
            return self._tool_meshes[tool_number]
        return self._default_tool_mesh

    def _log_tool_mesh_summary(self):
        """Log which tools used in the loaded file have real geometry vs. a fallback mesh."""
        used_tool_numbers = sorted({int(t) for t in self.raw_tools}) if self.raw_tools else []
        known = [t for t in used_tool_numbers if t in self._tool_meshes]
        unknown = [t for t in used_tool_numbers if t not in self._tool_meshes]
        unit_note = (
            f"; tool dimensions converted from inches (x{self.tool_unit_scale:g})"
            if self.tool_unit_scale != 1.0
            else ""
        )
        logger.info(
            f"Tool meshes ready: {len(known)}/{len(used_tool_numbers)} used tools have geometry "
            f"from the tool table ({known}); using default (pointed) mesh for {unknown}{unit_note}"
        )

    def _setup_pointer_gl_back(self, *args):
        """Draw back faces first so translucent tool surfaces sort correctly."""
        glEnable(GL_CULL_FACE)
        glCullFace(GL_FRONT)

    def _setup_pointer_gl_front(self, *args):
        """Draw front faces second, blending over the back faces."""
        glCullFace(GL_BACK)

    def _reset_pointer_gl(self, *args):
        glDisable(GL_CULL_FACE)
        glCullFace(GL_BACK)

    def _update_pointer_tool_mesh(self, vertex_idx):
        """Swap the pointer mesh geometry if the active tool changed."""
        if not self.pointer_mesh_instrs:
            return
        tool_number = self._tool_number_at_index(vertex_idx)
        if tool_number == self._active_tool_number:
            return
        vertices, indices, _fmt = self._get_tool_mesh(tool_number)
        for mesh in self.pointer_mesh_instrs:
            mesh.vertices = vertices
            mesh.indices = indices
        self._active_tool_number = tool_number
        self._scene_dirty = True

    def load_array(self, tmpdataarrs, is_end=True):
        self.clear_loaded_memery()

        dataarrs = []
        # Insert bridging segments when feed/rapid colors change
        last_color = -1
        last_line = -1
        for line in tmpdataarrs:
            color = line[4]

            need_regenerate = False
            if color >= 0 and last_color >= 0:
                if color != last_color:
                    need_regenerate = True

            if need_regenerate:
                replace_str = last_color
                copyline = line.copy()
                copyline[4] = last_color

                dataarrs.append(copyline)
                dataarrs.append(line)

            else:
                dataarrs.append(line)

            last_line = line
            last_color = color

        if is_end:
            self.clear_before_new_load = True
            self.clearDisplay(close_progress=False)
            self._add_canvas_children()

        self.meshmanager.add_data_arrs(dataarrs, is_end)

        if is_end:
            ff = self._get_line_vertex_fmt()

            self.lengths = self.meshmanager.lengths
            self.vertex_types = self.meshmanager.vertex_types
            self.positions = self.meshmanager.positions
            self.raw_positions = self.meshmanager.raw_positions
            self.raw_linenumbers = self.meshmanager.raw_linenumbers
            self.raw_feed_rates = self.meshmanager.raw_feed_rates
            self.raw_spindle_speeds = self.meshmanager.raw_spindle_speeds
            self.raw_tools = self.meshmanager.raw_tools
            self.angles_of_vertices = self.meshmanager.angles_of_vertices

            self.total_line_count = self.meshmanager.get_pt_count()
            self.total_distance = self.meshmanager.lengths[-1] if self.meshmanager.lengths else 0.0
            self.move_scale_by_positon = self.meshmanager.position_scale

            self.is_4_axis = self.meshmanager.is_4_axis

            # Compute per-segment durations from feed, XYZ travel, and A surface speed
            if self.high_precision_time_estimate and len(self.raw_feed_rates) >= len(self.raw_linenumbers or []):
                self._compute_line_times_async()

            self._update_feed_range_uniforms()

            self.axis_obj = ObjFile(AXIS_OBJ_PATH)

            # Build a basic 3D mesh per known tool (from CAM comments), plus a
            # default (basic pointed) mesh used for tools with no metadata.
            # tool_unit_scale converts inch tool dims into the mm coordinate space.
            self._tool_meshes, self._default_tool_mesh = build_tool_meshes(
                self.tool_table or {}, scale=self.move_scale_by_positon * self.tool_unit_scale
            )
            self._active_tool_number = self._tool_number_at_index(0)
            self._log_tool_mesh_summary()

            # 4-axis: rotate toolhead mesh instead of the toolpath
            self.rotate_line_or_knife = False
            if self.is_4_axis:
                self.rotate_line_or_knife = True

            with self.canvas:
                with self.linemesh:
                    self.cb = Callback(self.setup_gl_context)
                    for mesh in self.meshmanager.meshes:
                        Mesh(fmt=ff, vertices=mesh[0], indices=mesh[1], mode="line_strip")

                    self.cb = Callback(None)

                with self.pointermesh:
                    # Two-pass translucent draw: back faces, then front faces.
                    # A single pass fights the depth buffer and makes one side of the
                    # tool look hollow depending on camera orientation.
                    verts, idxs, fmt = self._get_tool_mesh(self._active_tool_number)
                    Callback(self._setup_pointer_gl_back)
                    back_mesh = Mesh(
                        vertices=verts,
                        indices=idxs,
                        fmt=fmt,
                        mode="triangles",
                    )
                    Callback(self._setup_pointer_gl_front)
                    front_mesh = Mesh(
                        vertices=verts,
                        indices=idxs,
                        fmt=fmt,
                        mode="triangles",
                    )
                    Callback(self._reset_pointer_gl)
                    self.pointer_mesh_instrs = [back_mesh, front_mesh]

                # axis
                with self.axisxmesh:
                    self.cb = Callback(None)
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode="triangles",
                    )
                    self.cb = Callback(None)
                with self.axisymesh:
                    self.cb = Callback(None)
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode="triangles",
                    )
                    self.cb = Callback(None)
                with self.axiszmesh:
                    self.cb = Callback(None)
                    m = list(self.axis_obj.objects.values())[0]
                    self.mesh = Mesh(
                        vertices=m.vertices,
                        indices=m.indices,
                        fmt=m.vertex_format,
                        mode="triangles",
                    )
                    self.cb = Callback(self.reset_gl_context)

            self.lines_center = self.meshmanager.get_center_of_view()
            self.linemesh["center_offset"] = Matrix().translate(
                -self.lines_center[0], -self.lines_center[1], -self.lines_center[2]
            )

            # rendering line meshes
            self.linemesh["display_count"] = -1.0
            self.reset_visibility_filters()

            self.pointermesh["offset"] = (-self.lines_center[0], -self.lines_center[1], -self.lines_center[2])

            # Stock mesh uses the newly computed scale/center; restart simulation if enabled.
            self._rebuild_bed_mesh()
            self._ensure_bed_on_canvas()
            self._rebuild_stock_mesh()
            self._ensure_stock_on_canvas()
            self._restart_stock_simulation()

            self.m_zoom = self._default_zoom_for_projection()
            self._clamp_zoom()
            self.update_proj()
            self.update_view()
            self._scene_dirty = True
            # force update
            self.canvas.ask_update()

    def update_proj(self):
        asp = self.size[0] / max(self.size[1], 1.0)
        proj = Matrix()
        zoomidx = self.m_zoom
        persp = 0 if self._ortho_projection else 1
        proj.view_clip(
            (-0.5 + self.m_xPan) * asp * zoomidx,
            (0.5 + self.m_xPan) * asp * zoomidx,
            (-0.5 + self.m_yPan) * zoomidx,
            (0.5 + self.m_yPan) * zoomidx,
            PROJ_NEAR,
            self.m_distance * 2,
            persp,
        )
        self._proj_matrix = proj
        self.linemesh["proj_mat"] = proj
        self.gridmesh["proj_mat"] = proj
        self.stockmesh["proj_mat"] = proj
        self.carvedmesh["proj_mat"] = proj
        self.bedmesh["proj_mat"] = proj
        self._update_grid_uniforms()
        self._update_bed_uniforms()
        self._update_stock_uniforms()
        self._update_carved_uniforms()
        self.pointermesh["projection_mat"] = proj
        self.axisxmesh["projection_mat"] = proj
        self.axisymesh["projection_mat"] = proj
        self.axiszmesh["projection_mat"] = proj

    def update_view(self):
        r = self.m_distance
        angY = -M_PI / 180.0 * self.m_yRot
        angX = M_PI / 180.0 * self.m_xRot

        eye = (
            r * math.cos(angX) * math.sin(angY) + self.m_xLookAt,
            r * math.cos(angX) * math.cos(angY) + self.m_yLookAt,
            r * math.sin(angX) + self.m_zLookAt,
        )

        center = (self.m_xLookAt, self.m_yLookAt, self.m_zLookAt)
        up = (
            -math.sin(angY + (M_PI if self.m_xRot < 0 else 0)) if abs(self.m_xRot) == 90 else 0,
            -math.cos(angY + (M_PI if self.m_xRot < 0 else 0)) if abs(self.m_xRot) == 90 else 0,
            math.cos(angX),
        )
        up = normalize(up)
        self.m_viewMatrix = Matrix().look_at(
            eye[0], eye[1], eye[2], center[0], center[1], center[2], up[0], up[1], up[2]
        )
        self._update_grid_uniforms()
        self._update_bed_uniforms()
        self._update_stock_uniforms()
        self._update_carved_uniforms()
        self._update_view_cube_uniforms()

    def setup_gl_context(self, *args):
        glViewport(self.pos[0] + self.off_x, self.pos[1] + self.off_y, self.size[0], self.size[1])
        glEnable(GL_DEPTH_TEST)

    def reset_gl_context(self, *args):
        # Depth mask is global GL state shared with carvedmesh / linemesh — always
        # restore writes after stock (translucent fill may have disabled them).
        glDepthMask(GL_TRUE)
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_CULL_FACE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glViewport(0, 0, Window.size[0], Window.size[1])

    # get total segment count
    def get_total_seg_count(self):
        return self.total_line_count

    # get max distance
    def get_total_distance(self):
        if not self.lengths:
            return 0.0
        return self.lengths[-1]

    # set display offset
    def set_display_offset(self, offx, offy):
        self.off_x = offx
        self.off_y = offy
        self._scene_dirty = True

    # set displaying limit
    def set_pos_by_distance(self, distance):
        if distance > self.get_total_distance():
            print("distance is out of bounds")
            return
        self.display_count = float(distance)
        self._scene_dirty = True
        # Sync cur_line_index to display_count so get_cur_pos_index() returns the correct line
        if self.lengths:
            cur_display_distance = float(self.display_count)
            line_index = binary_find_left(self.lengths, cur_display_distance)
            line_ratio = 0.0
            if line_index < len(self.lengths) - 1 and self.lengths[line_index + 1] > self.lengths[line_index]:
                line_ratio = (cur_display_distance - self.lengths[line_index]) / (
                    self.lengths[line_index + 1] - self.lengths[line_index]
                )
            self.cur_line_index = line_index + line_ratio
            self._sync_stock_simulation(int(self.cur_line_index))
        # Trigger frame callback to update line highlighting
        if self.frame_callback is not None:
            cur_distance, linenumber = self.get_cur_pos_index()
            self.frame_callback(cur_distance, linenumber)

    def _report_time_estimate_progress(self, state, percent):
        """Call the progress callback on the main thread (call from worker via Clock.schedule_once)."""
        if self.time_estimate_progress_callback is not None:
            self.time_estimate_progress_callback(state, percent)

    def _begin_line_times_job(self, show_progress, close_progress=True):
        """Bump the job id so in-flight workers become stale.

        When a silent job supersedes one that opened the progress popup, send 'done'
        so the popup closes. `close_progress` False only invalidates (e.g. a new file
        load already owns the same progress popup).
        """
        prev_show = self.line_times_job_show_progress
        self.line_times_job_id += 1
        self.line_times_job_show_progress = bool(show_progress)
        if close_progress and prev_show and not show_progress:
            self._report_time_estimate_progress("done", 100)
        return self.line_times_job_id

    def _line_times_job_is_current(self, job_id):
        return job_id is None or job_id == self.line_times_job_id

    def _apply_line_times_result(self, line_times, show_progress=True, job_id=None):
        """Apply worker result on main thread.

        `show_progress` True sends 'done' (caller closes the progress popup).
        False sends 'updated' so listeners can refresh without popup lifecycle.
        Stale `job_id` values are ignored so an older worker cannot overwrite a newer run.
        """
        if not self._line_times_job_is_current(job_id):
            return
        self.line_times = line_times if line_times else []
        self.total_time = self.line_times[-1] if self.line_times else 0.0
        self._invalidate_legend_durations()
        self.line_times_job_show_progress = False
        self._report_time_estimate_progress("done" if show_progress else "updated", 100)

    def _compute_line_times_async(self, show_progress=True):
        """
        Compute cumulative time (seconds) in a background thread so the UI stays responsive.
        Uses raw_feed_rates from the CNC parser (no file I/O). When *show_progress* is True,
        reports via time_estimate_progress_callback ('start', 'progress', 'done') and clears
        current times until the worker finishes. When False, keeps existing times on screen
        and reports 'updated' on apply (no popup).
        """
        n = len(self.raw_linenumbers) if self.raw_linenumbers else 0
        if n < 2 or not self.raw_positions or len(self.raw_positions) < n * 3:
            return
        if not self.raw_feed_rates or len(self.raw_feed_rates) < n:
            return
        job_id = self._begin_line_times_job(show_progress)
        if show_progress:
            self.line_times = []
            self.total_time = 0.0
            self._invalidate_legend_durations()
        raw_positions = list(self.raw_positions)
        raw_linenumbers = list(self.raw_linenumbers)
        raw_feed_rates = list(self.raw_feed_rates)
        angles = list(self.angles_of_vertices)
        limits = _axis_limits_from_app() or dict(DEFAULT_AXIS_LIMITS)
        viewer = self
        PROGRESS_INTERVAL = 100 if show_progress else 0

        def report(state, percent):
            def _on_main(dt):
                if not viewer._line_times_job_is_current(job_id):
                    return
                viewer._report_time_estimate_progress(state, percent)

            Clock.schedule_once(_on_main, 0)

        def worker():
            line_times = _compute_line_times_worker(
                raw_positions,
                raw_linenumbers,
                raw_feed_rates,
                (lambda pct: report("progress", pct)) if show_progress else None,
                PROGRESS_INTERVAL,
                angles,
                limits,
            )
            Clock.schedule_once(
                lambda dt: viewer._apply_line_times_result(line_times, show_progress=show_progress, job_id=job_id),
                0,
            )

        if show_progress:
            report("start", 0)
        threading.Thread(target=worker, daemon=True).start()

    def get_elapsed_time_by_distance(self, distance):
        """
        Return elapsed time (seconds) at the given display distance.
        Returns None if line_times are not available.
        """
        if not self.line_times or not self.lengths:
            return None
        if distance <= 0:
            return 0.0
        total_dist = self.lengths[-1]
        if total_dist <= 0 or distance >= total_dist:
            return self.total_time
        n = len(self.lengths)
        for i in range(n - 1):
            if self.lengths[i] <= distance <= self.lengths[i + 1]:
                seg_len = self.lengths[i + 1] - self.lengths[i]
                if seg_len <= 0:
                    return self.line_times[i] if i < len(self.line_times) else None
                fraction = (distance - self.lengths[i]) / seg_len
                t0 = self.line_times[i] if i < len(self.line_times) else 0.0
                t1 = self.line_times[i + 1] if i + 1 < len(self.line_times) else t0
                return t0 + fraction * (t1 - t0)
        return None

    def get_remaining_time_by_lineidx(self, line_number, ratio=0.5):
        """
        Return estimated remaining time (seconds) from the given line number.
        Uses distance/feed-based estimate when line_times are available.
        Returns None to fall back to machine estimate.
        """
        if not self.line_times or self.total_time <= 0:
            return None
        distance = self.get_distance_by_lineidx(line_number, ratio)
        if distance is None:
            return None
        elapsed = self.get_elapsed_time_by_distance(distance)
        if elapsed is None:
            return None
        return max(0.0, self.total_time - elapsed)

    def _invalidate_legend_durations(self):
        self.legend_durations_cache = None

    def _compute_all_legend_durations(self):
        """Return a dict of color_scheme -> {(kind, key): seconds}."""
        n = len(self.line_times)
        feeds = self.raw_feed_rates or []
        tools = self.raw_tools or []
        positions = self.positions or []

        feed_min = float(getattr(self, "feed_min", 0.0) or 0.0)
        feed_max = float(getattr(self, "feed_max", 0.0) or 0.0)
        if feed_max <= feed_min:
            feed_max = feed_min + 1.0

        z_min_mm = float(getattr(self, "z_min_mm", 0.0) or 0.0)
        z_max_mm = float(getattr(self, "z_max_mm", 0.0) or 0.0)
        if z_max_mm <= z_min_mm:
            z_max_mm = z_min_mm + 1.0

        by_scheme = {
            COLOR_SCHEME_BY_TYPE: {},
            COLOR_SCHEME_BY_TOOL: {},
            COLOR_SCHEME_BY_SPEED: {},
            COLOR_SCHEME_BY_Z: {},
        }

        def add(scheme, kind, key, duration):
            if duration <= 0.0:
                return
            entry_key = (kind, key)
            bucket = by_scheme[scheme]
            bucket[entry_key] = bucket.get(entry_key, 0.0) + duration

        for i in range(1, n):
            duration = float(self.line_times[i]) - float(self.line_times[i - 1])
            if duration <= 0.0:
                continue

            feed = 0.0
            if i < len(feeds):
                try:
                    feed = float(feeds[i])
                except (TypeError, ValueError):
                    feed = 0.0
            is_rapid = feed < 0.5

            tool = int(tools[i]) if i < len(tools) else -1
            add(COLOR_SCHEME_BY_TOOL, "tool", tool, duration)

            if is_rapid:
                add(COLOR_SCHEME_BY_TYPE, "rapid", "rapid", duration)
                add(COLOR_SCHEME_BY_SPEED, "rapid", "rapid", duration)
            else:
                add(COLOR_SCHEME_BY_TYPE, "feed", "feed", duration)
                add(
                    COLOR_SCHEME_BY_SPEED,
                    "speed_bucket",
                    _speed_bucket_index(feed, feed_min, feed_max),
                    duration,
                )
                z_mm = 0.0
                if len(positions) >= 3 * (i + 1):
                    z_mm = float(positions[3 * i + 2])
                add(
                    COLOR_SCHEME_BY_Z,
                    "z_bucket",
                    _z_bucket_index(z_mm, z_min_mm, z_max_mm),
                    duration,
                )

        return by_scheme

    def get_legend_durations(self, color_scheme=None):
        """
        Return cached segment-duration totals for one color-scheme legend (dict of (kind, key) -> seconds).
        If line_times are unavailable (eg high-precision estimate disabled / not finished / empty), returns None.
        """
        if not self.line_times or len(self.line_times) < 2:
            return None

        if self.legend_durations_cache is None:
            self.legend_durations_cache = self._compute_all_legend_durations()

        if color_scheme is None:
            color_scheme = self.color_scheme
        return self.legend_durations_cache.get(color_scheme, {})

    def get_distance_by_lineidx(self, lineidx, ratio):
        # Validate that we have the necessary data
        if not self.raw_linenumbers or not self.lengths:
            return None

        left_pos = binary_find_left(self.raw_linenumbers, lineidx)
        while left_pos > 0 and self.raw_linenumbers[left_pos - 1] == lineidx:
            left_pos = left_pos - 1

        right_pos = left_pos
        while right_pos < len(self.raw_linenumbers) - 1 and self.raw_linenumbers[right_pos + 1] == lineidx:
            right_pos = right_pos + 1
        # skip to next pos(lineidx+1)
        right_pos = right_pos + 1

        # Ensure bounds are valid since not all lines are movements
        if left_pos >= len(self.lengths):
            left_pos = len(self.lengths) - 1
        if right_pos >= len(self.lengths):
            right_pos = len(self.lengths) - 1
        if left_pos < 0:
            left_pos = 0
        if right_pos < 0:
            right_pos = 0

        # Ensure we have valid indices
        if left_pos >= len(self.lengths) or right_pos >= len(self.lengths):
            return None

        # start point
        start_distance = self.lengths[left_pos]
        end_distance = self.lengths[right_pos]

        return start_distance * (1.0 - ratio) + end_distance * ratio

    def set_distance_by_lineidx(self, lineidx, ratio):
        # Validate that we have the necessary data
        if not self.raw_linenumbers or not self.lengths:
            return

        left_pos = binary_find_left(self.raw_linenumbers, lineidx)
        while left_pos > 0 and self.raw_linenumbers[left_pos - 1] == lineidx:
            left_pos = left_pos - 1

        right_pos = left_pos
        while right_pos < len(self.raw_linenumbers) - 1 and self.raw_linenumbers[right_pos + 1] == lineidx:
            right_pos = right_pos + 1
        # skip to next pos(lineidx+1)
        right_pos = right_pos + 1

        # Ensure bounds are valid since not all lines are movements
        if left_pos >= len(self.lengths):
            left_pos = len(self.lengths) - 1
        if right_pos >= len(self.lengths):
            right_pos = len(self.lengths) - 1
        if left_pos < 0:
            left_pos = 0
        if right_pos < 0:
            right_pos = 0

        # Ensure we have valid indices
        if left_pos >= len(self.lengths) or right_pos >= len(self.lengths):
            return

        # start point
        start_distance = self.lengths[left_pos]
        end_distance = self.lengths[right_pos]

        cur_distance = start_distance * (1.0 - ratio) + end_distance * ratio
        self.set_pos_by_distance(cur_distance)

    def get_cur_pos_index(self):
        line_number = -1

        if self.cur_line_index < len(self.raw_linenumbers):
            line_number = self.raw_linenumbers[int(self.cur_line_index)]

        return [self.display_count, line_number]

    def enable_dynamic_displaying(self, dynamic_display):
        self.dynamic_display = dynamic_display
        self._scene_dirty = True

    def show_all(self):
        self.dynamic_display = False
        self.display_count = self.get_total_distance()
        self._scene_dirty = True

    def restore_default_view(self):
        self.m_xLookAt = 0
        self.m_yLookAt = 0
        self.m_zLookAt = 0
        self.m_xRot = 30
        self.m_yRot = 180
        self.m_zoom = self._default_zoom_for_projection()
        self._clamp_zoom()
        self.m_xPan = 0
        self.m_yPan = 0
        self.update_proj()
        self.update_view()
        self._scene_dirty = True

    def set_move_speed(self, mov_speed):
        self.move_speed = mov_speed

    def reset_visibility_filters(self, used_tools=None):
        """Show every path category; optionally seed the tool filter from used_tools."""
        self.show_rapid = True
        self.show_feed = True
        self.speed_bucket_bits = VISIBILITY_ALL_BUCKET_BITS
        self.z_bucket_bits = VISIBILITY_ALL_BUCKET_BITS
        tools = []
        if used_tools:
            tools = sorted({int(t) for t in used_tools if int(t) >= 0})[:VISIBILITY_MAX_TOOLS]
        self._tool_filter_ids = tools
        self._tool_filter_bits = (1 << len(tools)) - 1 if tools else 0
        self._apply_visibility_uniforms()
        self._scene_dirty = True

    def set_visibility_filters(
        self,
        *,
        show_rapid=None,
        show_feed=None,
        speed_bucket_bits=None,
        z_bucket_bits=None,
        tool_ids=None,
        tool_bits=None,
    ):
        """Update path visibility uniforms. Omitted args keep their current value."""
        if show_rapid is not None:
            self.show_rapid = bool(show_rapid)
        if show_feed is not None:
            self.show_feed = bool(show_feed)
        if speed_bucket_bits is not None:
            self.speed_bucket_bits = int(speed_bucket_bits) & VISIBILITY_ALL_BUCKET_BITS
        if z_bucket_bits is not None:
            self.z_bucket_bits = int(z_bucket_bits) & VISIBILITY_ALL_BUCKET_BITS
        if tool_ids is not None:
            self._tool_filter_ids = [int(t) for t in tool_ids][:VISIBILITY_MAX_TOOLS]
        if tool_bits is not None:
            max_bits = (1 << max(len(self._tool_filter_ids), 1)) - 1 if self._tool_filter_ids else 0
            self._tool_filter_bits = int(tool_bits) & max_bits if self._tool_filter_ids else 0
        self._apply_visibility_uniforms()
        self._scene_dirty = True

    def _apply_visibility_uniforms(self):
        mesh = self.linemesh
        mesh["show_rapid"] = 1.0 if self.show_rapid else 0.0
        mesh["show_feed"] = 1.0 if self.show_feed else 0.0
        mesh["speed_bucket_bits"] = float(self.speed_bucket_bits)
        mesh["z_bucket_bits"] = float(self.z_bucket_bits)

        ids = list(self._tool_filter_ids)[:VISIBILITY_MAX_TOOLS]
        packed = [0.0] * VISIBILITY_MAX_TOOLS
        for i, tool_id in enumerate(ids):
            packed[i] = float(tool_id)
        mesh["tool_filter_count"] = float(len(ids))
        mesh["tool_bits"] = float(self._tool_filter_bits if ids else 0)
        mesh["tool_ids0"] = packed[0:4]
        mesh["tool_ids1"] = packed[4:8]
        mesh["tool_ids2"] = packed[8:12]
        mesh["tool_ids3"] = packed[12:16]
        mesh["tool_ids4"] = packed[16:20]
        mesh["tool_ids5"] = packed[20:24]

    def _apply_color_scheme_uniform(self):
        self.linemesh["color_scheme"] = float(self.color_scheme)

    def _update_feed_range_uniforms(self):
        feeds = [float(f) for f in (self.raw_feed_rates or []) if f and float(f) > 0.0]
        if feeds:
            self.feed_min = min(feeds)
            self.feed_max = max(feeds)
        else:
            self.feed_min = 0.0
            self.feed_max = DEFAULT_FEED_MM_MIN
        if self.feed_max <= self.feed_min:
            self.feed_max = self.feed_min + 1.0
        self.linemesh["feed_min"] = float(self.feed_min)
        self.linemesh["feed_max"] = float(self.feed_max)
        self._update_z_range_uniforms()

    def _update_z_range_uniforms(self):
        """Height scheme: P5–P95 of feed-move Z (mm); shader uses Z * move_scale_by_positon."""
        scale = float(getattr(self, "move_scale_by_positon", 1.0) or 1.0)
        positions = getattr(self, "positions", None) or []
        feeds = getattr(self, "raw_feed_rates", None) or []
        self.z_min_mm, self.z_max_mm = _feed_z_height_range_mm(positions, feeds)

        self.z_min = self.z_min_mm * scale
        self.z_max = self.z_max_mm * scale
        if self.z_max <= self.z_min:
            self.z_max = self.z_min + max(scale, 1e-6)

        self.linemesh["z_min"] = float(self.z_min)
        self.linemesh["z_max"] = float(self.z_max)

    def raw_feed_z_max_mm(self) -> float | None:
        """P95 of feed-move Z in raw WCS millimetres (not A-baked display XYZ).

        ``z_max_mm`` is computed from display ``positions``, which already have
        A baked in. Rotary stock estimate must cap against machine Z instead.
        """
        positions = getattr(self, "raw_positions", None) or []
        feeds = getattr(self, "raw_feed_rates", None) or []
        if not positions or not feeds:
            return None
        _z_min, z_max = _feed_z_height_range_mm(positions, feeds)
        return float(z_max)

    def set_color_scheme(self, scheme):
        """Set toolpath color scheme from UI label or internal id."""
        if scheme in (COLOR_SCHEME_UI_BY_TOOL, "by_tool", COLOR_SCHEME_BY_TOOL):
            self.color_scheme = COLOR_SCHEME_BY_TOOL
        elif scheme in (COLOR_SCHEME_UI_BY_SPEED, "by_speed", COLOR_SCHEME_BY_SPEED):
            self.color_scheme = COLOR_SCHEME_BY_SPEED
        elif scheme in (COLOR_SCHEME_UI_BY_Z, "by_z", COLOR_SCHEME_BY_Z):
            self.color_scheme = COLOR_SCHEME_BY_Z
        else:
            self.color_scheme = COLOR_SCHEME_BY_TYPE
        self._apply_color_scheme_uniform()
        self._scene_dirty = True

    def simulation_available(self) -> bool:
        """True when cut simulation can run for the loaded file.

        Mill jobs need CAM tool geometry in ``tool_table``. Laser-only files
        have no mill headers, so an empty table is still enough when the parsed
        path uses only the laser (probe tools ignored).
        """
        if self.tool_table:
            return True
        return self._path_is_laser_only()

    def _path_is_laser_only(self) -> bool:
        """True if vertices use the laser and no mill tools (probes ignored)."""
        found_laser = False
        for tool in self.raw_tools or []:
            try:
                number = int(tool)
            except (TypeError, ValueError):
                continue
            if number == ZPROBE_TOOL_NUMBER or is_probe_tools_range(number):
                continue
            if number == LASER_TOOL_NUMBER:
                found_laser = True
                continue
            return False
        return found_laser

    def _apply_default_stock_settings(self) -> None:
        try:
            self.set_stock(
                default_bounds(),
                visible=False,
                simulate_cut=False,
                shape=default_shape(),
            )
        except Exception:
            logger.exception("failed to apply default stock settings")

    def set_stock(
        self,
        bounds: StockBounds | None,
        visible: bool = True,
        simulate_cut: bool = False,
        voxel_resolution: str = DEFAULT_VOXEL_RESOLUTION,
        checkpoint_level: str = DEFAULT_CHECKPOINT_LEVEL,
        mesh_while_playing: bool = False,
        carver_mode: str = DEFAULT_CARVER_MODE,
        shape: StockShape | None = None,
        material: str = DEFAULT_MATERIAL,
    ) -> None:
        """Configure stock display and optional cut simulation."""
        new_shape: StockShape | None
        if shape is not None:
            new_shape = shape
        elif bounds is not None and self.stock_shape is None:
            sx, sy, sz = bounds.size
            new_shape = RectangularStock(
                width_mm=max(sx, 1e-6),
                length_mm=max(sy, 1e-6),
                height_mm=max(sz, 1e-6),
            )
        else:
            new_shape = self.stock_shape
        stock_visible = bool(visible) and bounds is not None
        want_sim = bool(simulate_cut) and self.simulation_available() and stock_visible
        mesh_while = bool(mesh_while_playing)
        voxel_res = normalize_voxel_resolution(voxel_resolution)
        ckpt = normalize_checkpoint_level(checkpoint_level)
        carver = normalize_carver_mode(carver_mode)
        material = normalize_stock_material(material)

        carve_unchanged = (
            bounds == self.stock_bounds_mm
            and new_shape == self.stock_shape
            and want_sim == self.simulate_cut
            and mesh_while == self.stock_mesh_while_playing
            and voxel_res == self.stock_voxel_resolution
            and ckpt == self.stock_checkpoint_level
            and carver == self.stock_carver_mode
        )

        self.stock_bounds_mm = bounds
        self.stock_shape = new_shape
        self.stock_visible = stock_visible
        self.simulate_cut = want_sim
        self.stock_mesh_while_playing = mesh_while
        self.stock_voxel_resolution = voxel_res
        self.stock_checkpoint_level = ckpt
        self.stock_carver_mode = carver
        self.stock_material = material
        if not carve_unchanged:
            self._defer_carved_stock = False

        self._rebuild_stock_mesh()
        self._ensure_stock_on_canvas()
        self._update_carved_uniforms()
        if not carve_unchanged:
            self._restart_stock_simulation()
        self._scene_dirty = True
        self._sim_hud_trigger()

    def _format_sim_hud_text(self) -> str:
        if not self.simulate_cut or self._stock_simulator is None:
            return ""
        stats = self._stock_simulator.hud_stats()
        if not stats:
            return ""

        cell_mm = stats["cell_size_mm"]
        cell_txt = format_cell_size_mm(cell_mm)

        # Furthest checkpoint as path-distance percent (same basis as the scrubber ticks).
        head_pct = 0.0
        if int(stats["checkpoint_count"]) > 0:
            head_pct = self._vertex_to_path_percent(stats["checkpoint_head_vertex"])

        carver = str(stats.get("carver") or "voxel")
        if carver == "heightmap":
            grid_line = tr._("Heightmap: %dx%d - %smm/cell") % (
                int(stats.get("grid_nx", 0)),
                int(stats.get("grid_ny", 0)),
                cell_txt,
            )
        elif carver == "cylindrical":
            grid_line = tr._("Cylindrical: %dx%d - %s mm along X and at Ø%s") % (
                int(stats.get("grid_nx", 0)),
                int(stats.get("grid_ny", 0)),
                cell_txt,
                format_diameter_mm(float(stats["stock_diameter_mm"])),
            )
        else:
            grid_line = tr._("Grid: %dx%dx%d - %smm/voxel") % (
                int(stats["grid_nx"]),
                int(stats["grid_ny"]),
                int(stats["grid_nz"]),
                cell_txt,
            )

        return "\n".join(
            [
                grid_line,
                tr._("Checkpoints: %.0f%% - %d/%d slots")
                % (
                    head_pct,
                    int(stats["checkpoint_count"]),
                    int(stats["checkpoint_max_count"]),
                ),
            ]
        )

    def _refresh_sim_hud(self, *_args) -> None:
        self.sim_hud_text = self._format_sim_hud_text()

    def _vertex_to_path_percent(self, vertex: int) -> float:
        total = self.get_total_distance() if self.lengths else 0.0
        if total <= 0 or not self.lengths:
            return 0.0
        v = max(0, min(int(vertex), len(self.lengths) - 1))
        return float(self.lengths[v]) / float(total) * 100.0

    def _ensure_stock_on_canvas(self) -> None:
        if not self._viewer_meshes_active:
            return
        show_stock = self.stock_visible or self.simulate_cut
        show_voxels = self._carved_stock_visible()
        for mesh in (self.stockmesh, self.carvedmesh):
            if mesh in self.canvas.children:
                self.canvas.remove(mesh)
        if not show_stock:
            self._clear_carved_meshes()
            return
        try:
            if getattr(self, "bedmesh", None) is not None and self.bedmesh in self.canvas.children:
                idx = self.canvas.children.index(self.bedmesh) + 1
            else:
                idx = self.canvas.children.index(self.gridmesh) + 1
            self.canvas.insert(idx, self.stockmesh)
            if show_voxels:
                self.canvas.insert(idx + 1, self.carvedmesh)
        except ValueError:
            self.canvas.add(self.stockmesh)
            if show_voxels:
                self.canvas.add(self.carvedmesh)
        self._raise_view_cube_to_top()

    def set_bed(
        self,
        mesh_path: str | None,
        mcs_xyz: tuple[float, float, float] | None = None,
        material: str = "mdf",
        visible: bool = True,
    ) -> bool:
        """Show or hide the bed mesh in WCS.

        Vertices stay in model-local millimetres; MCS→WCS is applied via
        ``model_offset`` and WCS ``rotation_mat`` so a WCS change does not remesh.
        """
        if not visible or not mesh_path:
            self.bed_visible = False
            self._bed_mesh_path = None
            self._bed_loaded = None
            self._bed_wcs_applied = None
            self.bedmesh.clear()
            self._ensure_bed_on_canvas()
            self._scene_dirty = True
            return True
        try:
            loaded = load_bed_mesh(mesh_path)
        except (OSError, ValueError) as exc:
            logger.warning("failed to load bed mesh %s: %s", mesh_path, exc)
            self.bed_visible = False
            self._bed_mesh_path = None
            self._bed_loaded = None
            self._bed_wcs_applied = None
            self.bedmesh.clear()
            self._ensure_bed_on_canvas()
            self._scene_dirty = True
            return False
        self._bed_mesh_path = mesh_path
        self._bed_loaded = loaded
        self._bed_thickness_mm = float(loaded.thickness_mm)
        if mcs_xyz is not None:
            self._bed_mcs_xyz = (float(mcs_xyz[0]), float(mcs_xyz[1]), float(mcs_xyz[2]))
        self._bed_material = normalize_bed_material(material)
        self.bed_visible = True
        self._rebuild_bed_mesh()
        self._ensure_bed_on_canvas()
        self._scene_dirty = True
        return True

    def update_bed_wcs(self) -> None:
        """Refresh bed placement uniforms from live WCS (no remesh).

        Status packets call this often; skip the viewer dirty flag unless the
        origin actually moved so an idle scene is not redrawn every tick.
        """
        if not self.bed_visible:
            return
        wcs = self._read_wcs_origin()
        if self._bed_wcs_matches(wcs):
            return
        self._update_bed_uniforms()
        self._scene_dirty = True

    def _ensure_bed_on_canvas(self) -> None:
        if not self._viewer_meshes_active:
            return
        if self.bedmesh in self.canvas.children:
            self.canvas.remove(self.bedmesh)
        if not self.bed_visible:
            return
        try:
            idx = self.canvas.children.index(self.gridmesh) + 1
            self.canvas.insert(idx, self.bedmesh)
        except ValueError:
            self.canvas.add(self.bedmesh)
        self._raise_view_cube_to_top()

    def _rebuild_bed_mesh(self) -> None:
        self.bedmesh.clear()
        if not self.bed_visible or self._bed_loaded is None:
            return
        style = style_for_bed_material(self._bed_material)
        chunks = pack_bed_mesh_chunks(self._bed_loaded, self._stock_scale(), style.albedo_rgb)
        with self.bedmesh:
            Callback(self.setup_gl_context)
            Callback(self._setup_bed_gl)
            for vertices, indices in chunks:
                Mesh(fmt=BED_VERTEX_FORMAT, vertices=vertices, indices=indices, mode="triangles")
            Callback(self._reset_bed_gl)
            Callback(self.reset_gl_context)
        self._update_bed_uniforms()

    def _setup_bed_gl(self, *_args):
        glEnable(GL_DEPTH_TEST)
        glDepthMask(GL_TRUE)
        # Custom OBJs often have inverted or mixed winding. The shader already
        # two-sided-lights by flipping back-facing normals, so do not cull.
        glDisable(GL_CULL_FACE)
        glDisable(GL_BLEND)

    def _reset_bed_gl(self, *_args):
        glDisable(GL_CULL_FACE)
        glDepthMask(GL_TRUE)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def _wcs_rotation_matrix(self, rotation_angle_deg: float):
        angle = float(rotation_angle_deg or 0.0)
        if abs(angle) < 1e-6:
            return self._identity_mat
        mat = Matrix()
        mat.set(flat=list(wcs_rotation_4x4(angle)))
        return mat

    def _read_wcs_origin(self) -> tuple[float, float, float, float]:
        from .CNC import CNC

        vars_map: Any = CNC.vars
        return (
            float(vars_map.get("wcox") or 0.0),
            float(vars_map.get("wcoy") or 0.0),
            float(vars_map.get("wcoz") or 0.0),
            float(vars_map.get("rotation_angle") or 0.0),
        )

    def _bed_wcs_matches(self, wcs: tuple[float, float, float, float]) -> bool:
        prev = getattr(self, "_bed_wcs_applied", None)
        if prev is None:
            return False
        return all(abs(a - b) <= 1e-6 for a, b in zip(wcs, prev))

    def _update_bed_uniforms(self) -> None:
        if getattr(self, "bedmesh", None) is None:
            return
        center = getattr(self, "lines_center", [0.0, 0.0, 0.0])
        wcox, wcoy, wcoz, angle = self._read_wcs_origin()
        style = style_for_bed_material(self._bed_material)
        self.bedmesh["center_offset"] = Matrix().translate(-center[0], -center[1], -center[2])
        self.bedmesh["view_mat"] = self.m_viewMatrix
        self.bedmesh["proj_mat"] = self._proj_matrix
        self.bedmesh["rotation_mat"] = self._wcs_rotation_matrix(angle)
        self.bedmesh["model_offset"] = model_offset_viewer(self._bed_mcs_xyz, (wcox, wcoy, wcoz), self._stock_scale())
        self.bedmesh["metallic"] = float(style.metallic)
        self.bedmesh["roughness"] = float(style.roughness)
        self._bed_wcs_applied = (wcox, wcoy, wcoz, angle)

    def _stock_scale(self) -> float:
        return float(self.move_scale_by_positon or 1.0)

    def _mm_to_viewer(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        s = self._stock_scale()
        return (x * s, y * s, z * s)

    def _carved_stock_visible(self) -> bool:
        """True when opaque voxel stock should be drawn.

        During playback this follows ``stock_mesh_while_playing`` so low-end
        machines can keep the translucent AABB and skip live remesh. After
        pause, ``_defer_carved_stock`` keeps that AABB until the flush
        patches GPU chunks so the stale uncut shell is not flashed.
        """
        if self._defer_carved_stock:
            return False
        return bool(self.simulate_cut) and ((not self.dynamic_display) or bool(self.stock_mesh_while_playing))

    def _rebuild_stock_mesh(self) -> None:
        self.stockmesh.clear()
        if self.stock_bounds_mm is None:
            return

        b = self.stock_bounds_mm
        # Corners in viewer-scaled space (before center_offset).
        x0, y0, z0 = self._mm_to_viewer(b.min_x, b.min_y, b.min_z)
        x1, y1, z1 = self._mm_to_viewer(b.max_x, b.max_y, b.max_z)

        style = style_for_material(getattr(self, "stock_material", DEFAULT_MATERIAL))
        top_rgba, other_rgba, edge_rgba = preview_fill_rgba(style)

        shape = self.stock_shape
        if isinstance(shape, RotaryCylindricalStock):
            cy = 0.5 * (y0 + y1)
            cz = 0.5 * (z0 + z1)
            radius = 0.5 * min(abs(y1 - y0), abs(z1 - z0))
            edge_verts, edge_idx = build_x_cylinder_edges(cy, cz, x0, x1, radius, edge_rgba)
            fill_verts = fill_idx = None
            if not self._carved_stock_visible():
                fill_verts, fill_idx = build_x_cylinder_triangles(
                    cy, cz, x0, x1, radius, other_rgba, top_color=top_rgba
                )
        elif isinstance(shape, CylindricalStock):
            cx = 0.5 * (x0 + x1)
            cy = 0.5 * (y0 + y1)
            radius = 0.5 * min(abs(x1 - x0), abs(y1 - y0))
            edge_verts, edge_idx = build_cylinder_edges(cx, cy, z0, z1, radius, edge_rgba)
            fill_verts = fill_idx = None
            if not self._carved_stock_visible():
                fill_verts, fill_idx = build_cylinder_triangles(cx, cy, z0, z1, radius, other_rgba, top_color=top_rgba)
        else:
            edge_verts, edge_idx = build_box_edges(x0, y0, z0, x1, y1, z1, edge_rgba)
            fill_verts = fill_idx = None
            if not self._carved_stock_visible():
                fill_verts, fill_idx = build_box_triangles(x0, y0, z0, x1, y1, z1, other_rgba, top_color=top_rgba)

        with self.stockmesh:
            Callback(self.setup_gl_context)
            if fill_verts is not None:
                Callback(self._setup_stock_back_faces)
                Mesh(fmt=STOCK_VERTEX_FORMAT, vertices=fill_verts, indices=fill_idx, mode="triangles")
                Callback(self._setup_stock_front_faces)
                Mesh(fmt=STOCK_VERTEX_FORMAT, vertices=fill_verts, indices=fill_idx, mode="triangles")
            Callback(self._setup_stock_edges)
            Mesh(fmt=STOCK_VERTEX_FORMAT, vertices=edge_verts, indices=edge_idx, mode="lines")
            Callback(self.reset_gl_context)

        self._update_stock_uniforms()

    def _setup_stock_back_faces(self, *_args):
        glEnable(GL_CULL_FACE)
        glCullFace(GL_FRONT)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # Translucent AABB must not stamp depth or toolpath/voxels disappear.
        glDepthMask(GL_FALSE)
        self.stockmesh["use_lighting"] = 1.0

    def _setup_stock_front_faces(self, *_args):
        glCullFace(GL_BACK)
        glDepthMask(GL_FALSE)
        self.stockmesh["use_lighting"] = 1.0

    def _setup_stock_edges(self, *_args):
        glDisable(GL_CULL_FACE)
        # Edge lines should write depth; also safety before reset_gl_context.
        glDepthMask(GL_TRUE)
        self.stockmesh["use_lighting"] = 0.0

    def _set_stock_rotation_mat(self, mat) -> None:
        """Keep preview and voxel stock spinning with 4-axis playback."""
        self._stock_rotation_mat = mat
        self.stockmesh["rotation_mat"] = mat
        self.carvedmesh["rotation_mat"] = mat

    def _update_stock_uniforms(self) -> None:
        center = getattr(self, "lines_center", [0.0, 0.0, 0.0])
        self.stockmesh["center_offset"] = Matrix().translate(-center[0], -center[1], -center[2])
        self.stockmesh["view_mat"] = self.m_viewMatrix
        self.stockmesh["proj_mat"] = self._proj_matrix
        self.stockmesh["rotation_mat"] = self._stock_rotation_mat
        self.stockmesh["use_lighting"] = 1.0

    def _surface_z_eps_viewer(self) -> float:
        """Layer thickness in viewer-scaled millimetres (PCB foil / bicolor skin)."""
        style = style_for_material(getattr(self, "stock_material", DEFAULT_MATERIAL))
        thickness = max(float(style.surface_thickness_mm), 1e-4)
        return thickness * self._stock_scale()

    def _update_carved_uniforms(self) -> None:
        center = getattr(self, "lines_center", [0.0, 0.0, 0.0])
        self.carvedmesh["center_offset"] = Matrix().translate(-center[0], -center[1], -center[2])
        self.carvedmesh["view_mat"] = self.m_viewMatrix
        self.carvedmesh["proj_mat"] = self._proj_matrix
        self.carvedmesh["rotation_mat"] = self._stock_rotation_mat
        self.carvedmesh["vertex_scale"] = self._stock_scale()
        # Height tint range in the same viewer-scaled space as mesh vertex Z.
        bounds = self.stock_bounds_mm
        if bounds is not None:
            scale = self._stock_scale()
            self.carvedmesh["stock_z_min"] = float(bounds.min_z) * scale
            self.carvedmesh["stock_z_max"] = float(bounds.max_z) * scale
            self.carvedmesh["stock_xy_min"] = [float(bounds.min_x) * scale, float(bounds.min_y) * scale]
            self.carvedmesh["stock_xy_span"] = [
                max(float(bounds.size[0]) * scale, 1e-6),
                max(float(bounds.size[1]) * scale, 1e-6),
            ]
            self.carvedmesh["axis_yz"] = [
                0.5 * (float(bounds.min_y) + float(bounds.max_y)) * scale,
                0.5 * (float(bounds.min_z) + float(bounds.max_z)) * scale,
            ]
        else:
            self.carvedmesh["stock_z_min"] = 0.0
            self.carvedmesh["stock_z_max"] = 1.0
            self.carvedmesh["stock_xy_min"] = [0.0, 0.0]
            self.carvedmesh["stock_xy_span"] = [1.0, 1.0]
            self.carvedmesh["axis_yz"] = [0.0, 0.0]

        style = style_for_material(getattr(self, "stock_material", DEFAULT_MATERIAL))
        self.carvedmesh["surface_color"] = list(style.surface_rgb)
        self.carvedmesh["interior_color"] = list(style.resolved_interior_rgb())
        self.carvedmesh["use_two_tone"] = 1.0 if style.two_tone else 0.0
        self.carvedmesh["use_height_tint"] = 1.0 if style.use_height_tint else 0.0
        self.carvedmesh["metallic"] = float(style.metallic)
        self.carvedmesh["interior_metallic"] = float(style.resolved_interior_metallic())
        self.carvedmesh["roughness"] = float(style.roughness)
        self.carvedmesh["interior_roughness"] = float(style.resolved_interior_roughness())
        self.carvedmesh["surface_z_eps"] = self._surface_z_eps_viewer()
        rotary = isinstance(getattr(self, "stock_shape", None), RotaryCylindricalStock)
        self.carvedmesh["cylindrical_skin"] = 1.0 if rotary else 0.0
        radius = 0.0
        if bounds is not None and rotary:
            scale = self._stock_scale()
            radius = 0.5 * min(float(bounds.size[1]), float(bounds.size[2])) * scale
        self.carvedmesh["stock_radius"] = radius

    def _clear_carved_meshes(self) -> None:
        self.carvedmesh.clear()
        self._carved_meshes = {}
        # Keep GL setup/teardown callbacks so subsequent Mesh children render correctly.
        # Do not insert BindTexture here — Kivy Canvas.clear() then fails with
        # ValueError list.remove(x) when quality presets rebuild the simulation.
        with self.carvedmesh:
            Callback(self.setup_gl_context)
            Callback(self._setup_carved_gl)
            self._carved_mesh_anchor = Callback(None)
            Callback(self._reset_carved_gl)
            Callback(self.reset_gl_context)

    def _drop_laser_texture(self) -> None:
        self._laser_texture = None
        carved = getattr(self, "carvedmesh", None)
        if carved is not None:
            try:
                carved["laser_enabled"] = 0.0
            except Exception:
                pass

    def _apply_laser_payload(self, payload) -> None:
        if not payload:
            self._drop_laser_texture()
            return
        width, height, pixels, mode = payload
        self._laser_mode = str(mode)
        tex = self._laser_texture
        if tex is None or tex.size != (width, height):
            tex = Texture.create(size=(width, height), colorfmt="luminance", bufferfmt="ubyte")
            tex.mag_filter = "linear"
            tex.min_filter = "linear"
            self._laser_texture = tex
        tex.wrap = "repeat" if mode == "cylindrical" else "clamp_to_edge"
        tex.blit_buffer(pixels, colorfmt="luminance", bufferfmt="ubyte")
        self.carvedmesh["texture1"] = LASER_DECAL_TEXTURE_UNIT
        self.carvedmesh["laser_enabled"] = 1.0
        self.carvedmesh["laser_mode"] = 1.0 if mode == "cylindrical" else 0.0

    def _setup_carved_gl(self, *_args):
        # Opaque remaining-stock surfaces: depth writes so pocket floors are visible
        # instead of stacking translucent brown layers.
        glEnable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        tex = self._laser_texture
        if tex is not None:
            glActiveTexture(GL_TEXTURE0 + LASER_DECAL_TEXTURE_UNIT)
            tex.bind()
            glActiveTexture(GL_TEXTURE0)

    def _reset_carved_gl(self, *_args):
        glDisable(GL_CULL_FACE)
        glEnable(GL_BLEND)

    def _on_stock_meshes_ready(self, meshes: dict) -> None:
        """Called from the simulator worker thread — hop onto the Kivy clock."""
        # Capture generation so stale worker results are ignored after reset/disable.
        gen = self._stock_simulator.generation if self._stock_simulator else -1

        def _apply(_dt, meshes=meshes, gen=gen):
            if self._stock_simulator is None or self._stock_simulator.generation != gen:
                return
            self._apply_stock_meshes(meshes)

        Clock.schedule_once(_apply, 0)

    def _apply_stock_meshes(self, meshes: dict) -> None:
        # Special sentinels from disable / seek-back.
        if meshes and "__clear_all__" in meshes:
            self._drop_laser_texture()
            self._clear_carved_meshes()
            self._defer_carved_stock = False
            self._scene_dirty = True
            return
        laser_payload = None
        include_laser = False
        if meshes and "__laser__" in meshes:
            meshes = dict(meshes)
            laser_payload = meshes.pop("__laser__")
            include_laser = True
        reveal = self._defer_carved_stock
        # Keep GPU buffers in sync even when carvedmesh is off-canvas (play with
        # live mesh off). Hide by not drawing, not by dropping patches.
        if meshes and "__replace__" in meshes:
            self._clear_carved_meshes()
            meshes = meshes.get("__replace__") or {}
        for key, packed in meshes.items():
            existing = self._carved_meshes.get(key)
            if packed is None:
                if existing is not None:
                    self.carvedmesh.remove(existing)
                    del self._carved_meshes[key]
                continue
            vertices_mm, indices, fmt = packed
            if existing is not None:
                existing.vertices = vertices_mm
                existing.indices = indices
            else:
                mesh = Mesh(fmt=fmt or CARVED_VERTEX_FORMAT, vertices=vertices_mm, indices=indices, mode="triangles")
                # Insert before the reset callbacks (after the anchor).
                try:
                    anchor_idx = self.carvedmesh.children.index(self._carved_mesh_anchor)
                    self.carvedmesh.insert(anchor_idx + 1, mesh)
                except (ValueError, AttributeError):
                    self.carvedmesh.add(mesh)
                self._carved_meshes[key] = mesh
        if include_laser:
            self._apply_laser_payload(laser_payload)
        self._update_carved_uniforms()
        if reveal:
            self._reveal_carved_stock_if_deferred()
        self._scene_dirty = True

    def _reveal_carved_stock_if_deferred(self) -> None:
        """Swap AABB fill for voxels after a pause flush has patched GPU chunks."""
        if not self._defer_carved_stock:
            return
        self._defer_carved_stock = False
        self._rebuild_stock_mesh()
        self._ensure_stock_on_canvas()

    def _restart_stock_simulation(self) -> None:
        self._sim_carved_vertex = 0
        self._sim_progress_vertex = 0
        self.sim_progress = 0.0
        self.sim_checkpoints = []
        self._defer_carved_stock = False
        self._drop_laser_texture()
        self._clear_carved_meshes()
        if not self.simulate_cut or self.stock_bounds_mm is None:
            self._stock_simulator.disable()
            self._sim_hud_trigger()
            return
        self._publish_toolpath_to_simulator()
        self._stock_simulator.reset(
            self.stock_bounds_mm,
            enable=True,
            resolution_level=self.stock_voxel_resolution,
            checkpoint_slots=CHECKPOINT_SLOTS_BY_LEVEL[self.stock_checkpoint_level],
            shape=self.stock_shape,
            carver_mode=self.stock_carver_mode,
        )
        self._sync_play_mesh_policy(rebuild=False)
        if self.lengths and self.raw_positions:
            target = int(getattr(self, "cur_line_index", 0) or 0)
            self._stock_simulator.set_display_vertex(target)
            if not self.dynamic_display:
                self._stock_simulator.submit_idle_precompute(target)
        self._sim_hud_trigger()

    def _on_stock_progress(self, vertex: int) -> None:
        """Worker/UI progress emit — hop onto the Kivy clock with a generation stamp."""
        sim = self._stock_simulator
        gen = sim.generation if sim else -1
        v = int(vertex)

        def _apply(_dt, v=v, gen=gen):
            if self._stock_simulator is None or self._stock_simulator.generation != gen:
                return
            self._sim_progress_vertex = v
            self._sim_carved_vertex = v
            self._sim_progress_trigger()
            self._sim_hud_trigger()

        Clock.schedule_once(_apply, 0)

    def _sync_play_mesh_policy(self, *, rebuild: bool = True) -> None:
        """Match mesh emits / AABB fill to play vs pause and the live-mesh option."""
        sim = self._stock_simulator
        if sim is None:
            return
        if self.simulate_cut:
            playing = bool(self.dynamic_display)
            if playing:
                sim.set_idle_ahead_allowed(False)
                sim.cancel_idle_precompute()
            else:
                sim.set_idle_ahead_allowed(True)
            live = (not playing) or bool(self.stock_mesh_while_playing)
            sim.set_mesh_updates_enabled(live)
            sim.set_mesh_throttle_s(PLAY_MESH_THROTTLE_S if playing else DEFAULT_MESH_THROTTLE_S)
        if rebuild:
            self._rebuild_stock_mesh()
            self._ensure_stock_on_canvas()

    def _on_dynamic_display_changed(self, _instance, playing: bool) -> None:
        if playing or not self.simulate_cut or self.stock_mesh_while_playing:
            self._defer_carved_stock = False
        else:
            # Live mesh was off during play: keep the AABB until flush patches.
            self._defer_carved_stock = True
        self._sync_play_mesh_policy()
        if (not playing) and self.simulate_cut and self.raw_positions:
            target = int(getattr(self, "cur_line_index", 0) or 0)
            self._stock_simulator.set_display_vertex(target)
            self._stock_simulator.request_mesh_flush()
            self._stock_simulator.submit_idle_precompute(target)
        self._scene_dirty = True

    def _on_stock_checkpoints(self, vertices: list[int]) -> None:
        """Worker/UI checkpoint list — hop onto the Kivy clock with a generation stamp."""
        sim = self._stock_simulator
        gen = sim.generation if sim else -1
        verts = list(vertices or [])

        def _apply(_dt, verts=verts, gen=gen):
            if self._stock_simulator is None or self._stock_simulator.generation != gen:
                return
            self._pending_checkpoint_vertices = verts
            self._sim_checkpoints_trigger()
            self._sim_hud_trigger()

        Clock.schedule_once(_apply, 0)

    def _flush_sim_progress(self, *_args) -> None:
        if not self.simulate_cut:
            self.sim_progress = 0.0
            return
        self.sim_progress = self._vertex_to_path_percent(self._sim_progress_vertex)

    def _flush_sim_checkpoints(self, *_args) -> None:
        if not self.simulate_cut:
            self.sim_checkpoints = []
            return
        self.sim_checkpoints = [self._vertex_to_path_percent(vertex) for vertex in self._pending_checkpoint_vertices]

    def _publish_toolpath_to_simulator(self) -> None:
        """Hand the loaded path buffers to the worker (no copy — read-only after load)."""
        if self._stock_simulator is None:
            return
        # tool_unit_scale only (not move_scale_by_positon): carving is mm WCS.
        app = App.get_running_app()
        has_4axis = bool(app is not None and getattr(app, "has_4axis", False))
        has_off_axis_y = bool(app is not None and getattr(app, "has_off_axis_y", False))
        self._stock_simulator.set_toolpath(
            self.raw_positions,
            self.vertex_types,
            self.raw_tools,
            self.tool_table,
            tool_scale=float(self.tool_unit_scale or 1.0),
            angles=self.angles_of_vertices,
            has_4axis=has_4axis,
            has_off_axis_y=has_off_axis_y,
            speeds=self.raw_spindle_speeds,
        )

    def _sync_stock_simulation(self, current_vertex: int) -> None:
        if not self.simulate_cut or not self.raw_positions:
            return
        self._stock_simulator.set_display_vertex(max(0, int(current_vertex)))

    # repeat this function every 1/60 s
    def _on_frame_tick(self, _):
        # Recompute projection only when it is actually stale (resize / zoom / pan).
        if self._proj_dirty:
            self.update_proj()
            self._proj_dirty = False

        if self.lengths is None or len(self.lengths) <= 1:
            return

        # Skip the entire frame when nothing has changed and playback is paused.
        if not self.dynamic_display and not self._scene_dirty:
            return

        if self.dynamic_display:
            self.add_dir = self.move_speed * self.move_scale * self.move_scale_by_positon

            if self.display_count >= self.get_total_distance():
                self.dynamic_display = False
            else:
                self.display_count = self.display_count + self.add_dir

        self.linemesh["display_count"] = float(self.display_count)

        # which segment we are located
        cur_display_distance = float(self.display_count)
        line_index = binary_find_left(self.lengths, cur_display_distance)
        line_ratio = 0
        if line_index < len(self.lengths) - 1:
            segment_length = self.lengths[int(line_index) + 1] - self.lengths[int(line_index)]
            if segment_length == 0:
                if not self._cannot_visualise:
                    msg = "Gcode cannot be visualised due to parser error or gcode complexity.\n\nFeatures of the Controller that depend on visualisations have been disabled.\n\nFile playback can be attempted."
                    logger.error(msg)
                    if self.error_popup_callback is not None:
                        self.error_popup_callback(msg)
                    self._cannot_visualise = True
                self.dynamic_display = False
                return
            line_ratio = (cur_display_distance - self.lengths[int(line_index)]) / segment_length

        line_index_withratio = line_index + line_ratio

        self.cur_line_index = line_index_withratio
        self._sync_stock_simulation(int(line_index_withratio))

        self._update_pointer_tool_mesh(int(line_index_withratio))

        # Per-frame callback during toolpath playback only
        if self.frame_callback is not None and self.dynamic_display:
            [cur_distance, linenumber] = self.get_cur_pos_index()
            self.frame_callback(cur_distance, linenumber)

        if self.vertex_types[line_index] > 1.0:
            self.move_scale = 2.0
        else:
            self.move_scale = 1.0

        self.linemesh["rotation_mat"] = self._identity_mat

        self.linemesh["view_mat"] = self.m_viewMatrix
        self._update_grid_uniforms()
        self._update_bed_uniforms()
        self._update_stock_uniforms()
        self._update_carved_uniforms()

        pointer_updated_pos = 3 * int(line_index_withratio)

        self.pointermesh["rotation"] = self._identity_mat
        if pointer_updated_pos < len(self.positions):
            base_start = int(line_index_withratio)
            ratio = line_index_withratio - base_start
            offset = 0.0

            last_pos = vec3_sub(self.meshmanager.get_vertex_position(int(line_index_withratio)), self.lines_center)

            if self.is_4_axis:
                last_angle = self.angles_of_vertices[int(pointer_updated_pos / 3)]

            if ratio > 0.0 and pointer_updated_pos + 5 < len(self.positions):
                next_pos = vec3_sub(
                    self.meshmanager.get_vertex_position(int(line_index_withratio) + 1), self.lines_center
                )
                lerp_pos = [
                    next_pos[0] * ratio + (1.0 - ratio) * last_pos[0],
                    next_pos[1] * ratio + (1.0 - ratio) * last_pos[1],
                    next_pos[2] * ratio + (1.0 - ratio) * last_pos[2],
                ]
                self.pointermesh["offset"] = lerp_pos

                if self.is_4_axis:
                    next_angle = self.angles_of_vertices[int(pointer_updated_pos / 3) + 1]
                    lerp_angle = next_angle * ratio + (1.0 - ratio) * last_angle
                    if not self.rotate_line_or_knife:
                        self.pointermesh["rotation"] = rotate_mat_by_x_axis_angle(lerp_angle)
                    else:
                        rot = rotate_mat_by_x_axis_angle(-lerp_angle)
                        self.linemesh["rotation_mat"] = rot
                        self._set_stock_rotation_mat(rot)
                        len_to_center = len_2d(
                            [lerp_pos[1], lerp_pos[2]], [-self.lines_center[1], -self.lines_center[2]]
                        )
                        rot_point = self.linemesh["rotation_mat"].transform_point(lerp_pos[0], lerp_pos[1], lerp_pos[2])

                        self.pointermesh["offset"] = rot_point
            else:
                if self.is_4_axis:
                    if not self.rotate_line_or_knife:
                        self.pointermesh["rotation"] = rotate_mat_by_x_axis_angle(last_angle)
                    else:
                        rot = rotate_mat_by_x_axis_angle(-last_angle)
                        self.linemesh["view_mat"] = self.linemesh["view_mat"].multiply(rot)
                        self._set_stock_rotation_mat(rot)

                        len_to_center = len_3d(last_pos, [-self.lines_center[0], -self.lines_center[1], 0])
                        self.pointermesh["offset"] = [
                            -self.lines_center[0],
                            -self.lines_center[1],
                            len_to_center - self.lines_center[2],
                        ]

        self.pointermesh["modelview_mat"] = self.m_viewMatrix

        # axis
        axis_offset = (-self.lines_center[0], -self.lines_center[1], -self.lines_center[2])
        self.axisxmesh["offset"] = axis_offset
        self.axisxmesh["rotation"] = self._identity_mat
        self.axisxmesh["diff_color"] = AXIS_COLOR_Y

        self.axisymesh["offset"] = axis_offset
        self.axisymesh["rotation"] = self._axis_y_rot
        self.axisymesh["diff_color"] = AXIS_COLOR_Z

        self.axiszmesh["offset"] = axis_offset
        self.axiszmesh["rotation"] = self._axis_z_rot
        self.axiszmesh["diff_color"] = AXIS_COLOR_X

        self.axisxmesh["modelview_mat"] = self.m_viewMatrix
        self.axisymesh["modelview_mat"] = self.m_viewMatrix
        self.axiszmesh["modelview_mat"] = self.m_viewMatrix

        self.g_old_curosr = self.g_cursor
        self.g_wheel_data = 0
        self._scene_dirty = False

    # mouse event
    #
    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            try:
                if self._handle_view_cube_touch(touch):
                    return True

                touch.ud[TOUCH_CLAIMED] = True
                touchpos = [touch.pos[0], self.size[1] - touch.pos[1]]
                self.m_lastPos = touchpos.copy()
                self.m_xLastRot = self.m_xRot
                self.m_yLastRot = self.m_yRot
                self.m_xLastPan = self.m_xPan
                self.m_yLastPan = self.m_yPan

                if "button" in touch.profile:
                    if touch.is_mouse_scrolling:
                        if touch.button == "scrolldown":
                            self.zoom_out()
                        elif touch.button == "scrollup":
                            self.zoom_in()

                self.update_proj()
                self.update_view()
                self._scene_dirty = True

                if touch.is_double_tap:
                    self.restore_default_view()

            except:
                print(sys.exc_info()[1])

    def on_touch_move(self, touch):
        if touch.ud.get(TOUCH_CLAIMED) and self.collide_point(*touch.pos):
            try:
                touchpos = [touch.pos[0], self.size[1] - touch.pos[1]]

                if not "button" in touch.profile or touch.button == "left":
                    if self.orbit:
                        self.m_yRot = normalize_angle(self.m_yLastRot - (touchpos[0] - self.m_lastPos[0]) * 0.5)
                        self.m_xRot = self.m_xLastRot + (touchpos[1] - self.m_lastPos[1]) * 0.5

                        if self.m_xRot < -90:
                            self.m_xRot = -90.0
                        if self.m_xRot > 90:
                            self.m_xRot = 90.0

                        self.update_view()
                    else:
                        self.m_xPan = self.m_xLastPan - (touchpos[0] - self.m_lastPos[0]) * 1 / self.size[0]
                        self.m_yPan = self.m_yLastPan + (touchpos[1] - self.m_lastPos[1]) * 1 / self.size[1]

                        self.update_proj()

                elif "button" in touch.profile and touch.button == "right":
                    self.m_xPan = self.m_xLastPan - (touchpos[0] - self.m_lastPos[0]) * 1 / self.size[0]
                    self.m_yPan = self.m_yLastPan + (touchpos[1] - self.m_lastPos[1]) * 1 / self.size[1]

                    self.update_proj()

                self.g_cursor = [touch.pos[0], touch.pos[1]]
                self._scene_dirty = True
            except:
                print(sys.exc_info()[1])

    def on_touch_up(self, touch):
        if touch.ud.get(TOUCH_CLAIMED) and self.collide_point(*touch.pos):
            try:
                self.g_old_curosr = self.g_cursor = [touch.pos[0], touch.pos[1]]
            except:
                print(sys.exc_info()[1])

    def zoom_in(self):
        lo, _ = self._zoom_bounds()
        if self.m_zoom > lo:
            self.m_zoom /= ZOOMSTEP
            self.update_proj()
            self.update_view()
            self._scene_dirty = True

    def zoom_out(self):
        _, hi = self._zoom_bounds()
        if self.m_zoom < hi:
            self.m_zoom *= ZOOMSTEP
            self.update_proj()
            self.update_view()
            self._scene_dirty = True

    def set_orbit(self, orbit=True):
        self.orbit = orbit

    def set_grid_visible(self, visible=True):
        visible = bool(visible)
        if visible == self._grid_visible:
            return
        self._grid_visible = visible
        Config.set("carvera", CONFIG_GRID_VISIBLE_KEY, "1" if visible else "0")
        Config.write()
        self._update_grid_uniforms()
        self._scene_dirty = True

    def is_grid_visible(self):
        return self._grid_visible

    def _ortho_zoom_factor(self):
        """Ortho zoom is r/PROJ_NEAR larger than perspective for the same apparent
        scale at the look-at distance; perspective factor is 1."""
        if not self._ortho_projection:
            return 1.0
        r = max(self.m_distance, PROJ_NEAR + 1e-6)
        return r / PROJ_NEAR

    def _zoom_bounds(self):
        """Zoom clamp scaled by the projection factor so the usable zoom range is
        equivalent in ortho and perspective (raw MIN/MAX_ZOOM are perspective units)."""
        factor = self._ortho_zoom_factor()
        return MIN_ZOOM * factor, MAX_ZOOM * factor

    def _clamp_zoom(self):
        lo, hi = self._zoom_bounds()
        self.m_zoom = max(lo, min(hi, self.m_zoom))

    def _default_zoom_for_projection(self):
        """DEFAULT_ZOOM adjusted for the active projection so resets keep the same
        apparent scale as the perspective default (ortho needs r/PROJ_NEAR more zoom)."""
        return DEFAULT_ZOOM * self._ortho_zoom_factor()

    def _zoom_for_projection_switch(self, to_ortho):
        """Match apparent scale at the look-at distance when toggling projection."""
        r = max(self.m_distance, PROJ_NEAR + 1e-6)
        if to_ortho:
            return self.m_zoom * r / PROJ_NEAR
        return self.m_zoom * PROJ_NEAR / r

    def set_ortho_projection(self, ortho=True):
        ortho = bool(ortho)
        if ortho == self._ortho_projection:
            return
        self.m_zoom = self._zoom_for_projection_switch(ortho)
        self._ortho_projection = ortho
        self._clamp_zoom()
        self.update_proj()
        self._scene_dirty = True


def _clamp01(value):
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _speed_bucket_index(feed, feed_min, feed_max):
    """Match toolpath.glsl speed-bucket indexing (0..10)."""
    feed_span = max(float(feed_max) - float(feed_min), 1.0)
    feed_t = _clamp01((float(feed) - float(feed_min)) / feed_span)
    bucket = int(math.floor(feed_t * 10.0 + 0.5))
    return min(max(bucket, 0), VISIBILITY_BUCKET_COUNT - 1)


def _z_bucket_index(z_mm, z_min_mm, z_max_mm):
    """Match toolpath.glsl height-bucket indexing (0=high Z .. 10=low Z)."""
    z_span = float(z_max_mm) - float(z_min_mm)
    if z_span < 1e-6:
        z_span = 1e-6
    z_t = _clamp01((float(z_mm) - float(z_min_mm)) / z_span)
    bucket = int(math.floor((1.0 - z_t) * 10.0 + 0.5))
    return min(max(bucket, 0), VISIBILITY_BUCKET_COUNT - 1)


def _axis_limits_from_settings(setting_list):
    """Return {x,y,z,a,seek} in mm/min (A in deg/min), or None if config is incomplete."""
    if not setting_list:
        return None
    try:
        x = float(setting_list["alpha_max_rate"])
        y = float(setting_list["beta_max_rate"])
        z = float(setting_list["gamma_max_rate"])
        a = float(setting_list["delta_max_rate"])
    except (KeyError, TypeError, ValueError):
        return None
    seek = DEFAULT_FEED_MM_MIN
    raw_seek = setting_list.get("default_seek_rate")
    if raw_seek is not None:
        try:
            seek = float(raw_seek)
        except (TypeError, ValueError):
            pass
    if min(x, y, z, a, seek) <= 0.0:
        return None
    return {"x": x, "y": y, "z": z, "a": a, "seek": seek}


def _axis_limits_from_app():
    """Machine max rates from config, or C1 defaults when config is missing."""
    app = App.get_running_app()
    setting_list = None
    if app is not None:
        setting_list = getattr(app, "setting_list", None)
        if not setting_list:
            root = getattr(app, "root", None)
            setting_list = getattr(root, "setting_list", None)
    return _axis_limits_from_settings(setting_list) or dict(DEFAULT_AXIS_LIMITS)


def _a_surface_arc_mm(target_pos, da_deg):
    """Arc length at the target WCS Y/Z radius. Firmware uses 2π when r <= 0.1 mm."""
    radius = math.hypot(float(target_pos[1]), float(target_pos[2]))
    perimeter = 2.0 * math.pi if radius <= ROTARY_RADIUS_EPS_MM else 2.0 * math.pi * radius
    return perimeter * abs(float(da_deg)) / 360.0


def _segment_duration_sec(pos1, pos2, a1, a2, feed, limits=None):
    """Segment time (seconds) matching Carvera feed planning outcomes.

    G1 with A uses surface speed max(xyz, arc)/F. G0 skips that and uses XYZ
    length, or |dA| as millimetres when XYZ is parked. Axis max rates lengthen
    the move when *limits* is provided (callers always pass machine config
    or C1 defaults; None skips clamping for isolated formula tests).
    """
    dx = float(pos2[0]) - float(pos1[0])
    dy = float(pos2[1]) - float(pos1[1])
    dz = float(pos2[2]) - float(pos1[2])
    da = abs(float(a2) - float(a1))
    xyz = math.hypot(dx, dy, dz)

    seek = DEFAULT_FEED_MM_MIN
    if limits is not None:
        try:
            seek = float(limits["seek"])
        except (KeyError, TypeError, ValueError):
            pass
        if seek <= 0.0:
            seek = DEFAULT_FEED_MM_MIN

    is_rapid = True
    try:
        feed_val = float(feed)
        is_rapid = feed_val < MIN_FEED_MM_MIN
    except (TypeError, ValueError):
        feed_val = 0.0

    if is_rapid:
        programmed = seek
        path = xyz if xyz > MOVE_EPS_MM else da
        duration_min = path / programmed if programmed > 0.0 else 0.0
    else:
        programmed = feed_val
        if da > MOVE_EPS_MM:
            arc = _a_surface_arc_mm(pos2, da)
            duration_min = max(xyz, arc) / programmed
        else:
            duration_min = xyz / programmed

    if limits is not None:
        for delta, key in ((abs(dx), "x"), (abs(dy), "y"), (abs(dz), "z"), (da, "a")):
            try:
                axis_max = float(limits[key])
            except (KeyError, TypeError, ValueError):
                continue
            if axis_max > 0.0 and delta > 0.0:
                duration_min = max(duration_min, delta / axis_max)

    return duration_min * 60.0


def _compute_line_times_worker(
    raw_positions, raw_linenumbers, raw_feed_rates, progress_callback, progress_interval, angles=None, limits=None
):
    """
    Core logic for line time computation. Can run in a thread.
    Uses feed rates from raw_feed_rates (from CNC parser); no file I/O.
    `angles` is optional per-vertex A (degrees), same length as raw_linenumbers.
    `limits` is optional {x,y,z,a,seek} max rates (mm/min; A in deg/min).
    progress_callback(percent) is called every progress_interval segments; use 0 to disable.
    Returns list of cumulative times (line_times).
    """
    n = len(raw_linenumbers)
    line_times = [0.0]
    use_angles = angles is not None and len(angles) >= n
    for i in range(1, n):
        pos1 = [
            raw_positions[3 * (i - 1)],
            raw_positions[3 * (i - 1) + 1],
            raw_positions[3 * (i - 1) + 2],
        ]
        pos2 = [
            raw_positions[3 * i],
            raw_positions[3 * i + 1],
            raw_positions[3 * i + 2],
        ]
        a1 = angles[i - 1] if use_angles else 0.0
        a2 = angles[i] if use_angles else 0.0
        feed = 0.0
        if raw_feed_rates and i < len(raw_feed_rates):
            try:
                feed = float(raw_feed_rates[i])
            except (ValueError, TypeError):
                feed = 0.0
        duration_sec = _segment_duration_sec(pos1, pos2, a1, a2, feed, limits)
        line_times.append(line_times[-1] + duration_sec)
        if progress_callback and progress_interval > 0 and i % progress_interval == 0:
            progress_callback(100.0 * i / n)
    if progress_callback and progress_interval > 0 and n > 1:
        progress_callback(100.0)
    return line_times


if __name__ == "__main__":

    class MyApp(App):
        def build(self):
            viewer = GCodeViewer()
            viewer.set_play_over_callback(frame_call_back_test)
            lines = []
            with open("parsernew/gcodes(1).txt") as file:
                content = file.read()[2:-2]
                for line in content.split("], ["):
                    arr = line.split(",")
                    lines.append(
                        [
                            float(arr[0]),
                            float(arr[1]),
                            float(arr[2]),
                            float(arr[3]),
                            float(arr[4]),
                            float(arr[5]),
                            float(arr[6]),
                        ]
                    )

            get_elapsed("start")
            step = 10000
            for i in range(len(lines) // step + 1):
                start_idx = i * step
                end_idx = min((i + 1) * step, len(lines))
                viewer.load_array(lines[start_idx:end_idx], end_idx == len(lines))
            get_elapsed("loaded")

            viewer.set_distance_by_lineidx(1000, 0.5)
            viewer.show_all()
            return viewer

    MyApp().run()
