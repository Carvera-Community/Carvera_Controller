"""Based on the example https://github.com/mp-007/kivy_matplotlib_widget/tree/main/examples/example_live_data"""

import copy
import math
from typing import Any, Optional
from weakref import WeakKeyDictionary

import matplotlib

matplotlib.use("Agg")  # must be set before importing pyplot or backends
import matplotlib.lines as mlines  # noqa: E402
import matplotlib.pyplot  # noqa: E402
import numpy as np  # noqa: E402
from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402
from kivy.graphics.texture import Texture  # noqa: E402
from kivy.graphics.transformation import Matrix  # noqa: E402
from kivy.lang import Builder  # noqa: E402
from kivy.metrics import dp  # noqa: E402
from kivy.properties import (  # noqa: E402
    AliasProperty,
    BooleanProperty,
    BoundedNumericProperty,
    DictProperty,
    ListProperty,
    NumericProperty,
    ObjectProperty,
    OptionProperty,
)
from kivy.uix.widget import Widget  # noqa: E402
from kivy.utils import get_color_from_hex  # noqa: E402
from kivy.vector import Vector  # noqa: E402
from matplotlib import cbook  # noqa: E402
from matplotlib.backend_bases import ResizeEvent  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402

selector_widgets_available = False
try:
    selector_widgets_available = True
    from kivy_matplotlib_widget.uix.selector_widget import (  # noqa: E402
        EllipseRelativeLayout,
        LassoRelativeLayout,
        ResizeRelativeLayout,
        SpanRelativeLayout,
    )
except ImportError:
    print("Selector widgets are not available")


class MatplotlibEvent:
    x: Any = None
    y: Any = None
    pickradius: Any = None
    inaxes: Any = None
    projection: bool = False
    compare_xdata: bool = False
    pick_radius_axis: str = "both"


class MatplotFigureTwinx(Widget):  # type: ignore[misc]
    """Widget to show a matplotlib figure in kivy.
    The figure is rendered internally in an AGG backend then
    the rgba data is obtained and blitted into a kivy texture.
    """

    figure = ObjectProperty(None)
    _box_pos = ListProperty([0, 0])
    _box_size = ListProperty([0, 0])
    _img_texture = ObjectProperty(None)
    _alpha_box = NumericProperty(0)
    _bitmap = None
    _pressed = False
    do_update = False
    figcanvas = ObjectProperty(None)
    translation_touches = BoundedNumericProperty(1, min=1)
    do_scale = BooleanProperty(True)
    scale_min = NumericProperty(0.01)
    scale_max = NumericProperty(1e20)
    transform = ObjectProperty(Matrix())
    _alpha_hor = NumericProperty(0)
    _alpha_ver = NumericProperty(0)
    pos_x_rect_hor = NumericProperty(0)
    pos_y_rect_hor = NumericProperty(0)
    pos_x_rect_ver = NumericProperty(0)
    pos_y_rect_ver = NumericProperty(0)
    invert_rect_ver = BooleanProperty(False)
    invert_rect_hor = BooleanProperty(False)
    legend_do_scroll_x = BooleanProperty(True)
    legend_do_scroll_y = BooleanProperty(True)
    interactive_axis = BooleanProperty(False)
    do_pan_x = BooleanProperty(True)
    do_pan_y = BooleanProperty(True)
    do_zoom_x = BooleanProperty(True)
    do_zoom_y = BooleanProperty(True)
    fast_draw = BooleanProperty(True)  # True will don't draw axis
    xsorted = BooleanProperty(False)  # to manage x sorted data
    minzoom = NumericProperty(dp(20))
    twinx = BooleanProperty(False)
    compare_xdata = BooleanProperty(False)
    hover_instance = ObjectProperty(None, allownone=True)
    nearest_hover_instance = ObjectProperty(None, allownone=True)
    compare_hover_instance = ObjectProperty(None, allownone=True)
    disable_mouse_scrolling = BooleanProperty(False)
    disable_double_tap = BooleanProperty(False)
    text_instance = None
    min_max_option = BooleanProperty(True)
    auto_zoom = BooleanProperty(False)
    zoom_angle_detection = NumericProperty(15)  # in degree
    auto_cursor = BooleanProperty(False)
    autoscale_visible_only = BooleanProperty(True)
    autoscale_axis = OptionProperty("both", options=["both", "x", "y"])
    autoscale_tight = BooleanProperty(False)
    desktop_mode = BooleanProperty(True)  # change mouse hover for selector widget
    current_selector = OptionProperty("None", options=["None", "rectangle", "lasso", "ellipse", "span", "custom"])
    highlight_hover = BooleanProperty(False)
    highlight_prop = DictProperty({})
    highlight_alpha = NumericProperty(0.2)
    myevent = MatplotlibEvent()
    pick_minimum_radius = NumericProperty(dp(50))
    pick_radius_axis = OptionProperty("both", options=["both", "x", "y"])

    def on_figure(self, _obj: Any, _value: Any) -> None:
        self.figcanvas = _FigureCanvas(self.figure, self)
        self.figcanvas._isDrawn = False
        _left, _b, w, h = self.figure.bbox.bounds
        w = int(math.ceil(w))
        h = int(math.ceil(h))
        self.width = w
        self.height = h

        if len(self.figure.axes) > 0 and self.figure.axes[0]:
            # add copy patch
            ax = self.figure.axes[0]
            self.axes = ax
            patch_cpy = copy.copy(ax.patch)
            patch_cpy.set_visible(False)
            for pos in ["right", "top", "bottom", "left"]:
                ax.spines[pos].set_zorder(10)
            patch_cpy.set_zorder(9)
            self.background_patch_copy = ax.add_patch(patch_cpy)

            # set default xmin/xmax and ymin/ymax
            self.xmin, self.xmax = ax.get_xlim()
            self.ymin, self.ymax = ax.get_ylim()

            if len(self.figure.axes) == 2:
                self.twinx = True
                ax2 = self.figure.axes[1]
                patch_cpy_ax2 = copy.copy(ax2.patch)
                patch_cpy_ax2.set_visible(False)
                for pos in ["right", "top", "bottom", "left"]:
                    ax2.spines[pos].set_zorder(10)
                patch_cpy_ax2.set_zorder(9)
                self.background_ax2_patch_copy = ax2.add_patch(patch_cpy_ax2)
                self.ymin2, self.ymax2 = ax.get_ylim()
            else:
                self.twinx = False
                self.background_ax2_patch_copy = None
                self.ymin2 = None
                self.ymax2 = None

        if self.legend_instance:
            # remove all legend_instance from parent widget
            for current_legend in self.legend_instance:
                current_legend.parent.remove_widget(current_legend)
            self.legend_instance: list[Any] = []

        if self.auto_cursor:
            if len(self.figure.axes) == 2:
                self.register_lines(list(self.figure.axes[0].lines + self.figure.axes[1].lines))
            elif len(self.figure.axes) > 0:
                self.register_lines(list(self.figure.axes[0].lines))

        # Texture
        self._img_texture = Texture.create(size=(w, h))

        if self.selector and self.axes:
            self.selector.resize_wgt.ax = self.axes

        # close last figure in memory (avoid max figure warning)
        matplotlib.pyplot.close()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # figure info
        self.figure = None
        self.axes = None
        self.xmin = None
        self.xmax = None
        self.ymin = None
        self.ymax = None
        self.ymin2 = None
        self.ymax2 = None
        self.lines: list[Any] = []

        # option
        self.touch_mode = "pan"
        self.hover_on = False
        self.cursor_xaxis_formatter = None  # used matplotlib formatter to display x cursor value
        self.cursor_yaxis_formatter = None  # used matplotlib formatter to display y cursor value (left axis)
        self.cursor_yaxis2_formatter = None  # used matplotlib formatter to display y cursor value (right axis)

        # zoom box coordonnate
        self.x0_box = None
        self.y0_box = None
        self.x1_box = None
        self.y1_box = None

        # clear touches on touch up
        self._touches: list[Any] = []
        self._last_touch_pos: dict[Any, Any] = {}

        # background
        self.background = None
        self.background_patch_copy = None
        self.background_ax2_patch_copy = None

        # twin x axis
        self.twinx = False

        # manage adjust x and y
        self.anchor_x: Optional[str] = None
        self.anchor_y: Optional[str] = None

        # manage hover data
        self.x_hover_data = None
        self.y_hover_data = None

        # pan management
        self.first_touch_pan: Optional[str] = None

        # trick to manage wrong canvas size on first call (compare_hover)
        self.first_call_compare_hover = False

        # cross hair cursor
        self.horizontal_line: Any = None
        self.vertical_line: Any = None

        # manage cursor update on right axis
        self.cursor_last_axis = None
        self.cursor_last_y = 0

        # manage show compare cursor on release
        self.show_compare_cursor = False

        # manage back and next event
        _stack_cls = cbook._Stack if hasattr(cbook, "_Stack") else cbook.Stack  # type: ignore[attr-defined]
        self._nav_stack: Any = _stack_cls()
        self.set_history_buttons()

        # legend management
        self.legend_instance = []
        self.current_legend = None

        # selector management
        self.kv_post_done = False
        self.selector: Any = None

        # highlight management
        self.last_line: Any = None
        self.last_line_prop: dict[str, Any] = {}

        self.bind(size=self._on_size)

    def on_kv_post(self, _: Any) -> None:
        # if not self.selector:
        if self.current_selector != "None" and selector_widgets_available:
            if self.current_selector == "rectangle":
                self.set_selector(ResizeRelativeLayout)
            elif self.current_selector == "lasso":
                self.set_selector(LassoRelativeLayout)
            elif self.current_selector == "ellipse":
                self.set_selector(EllipseRelativeLayout)
            elif self.current_selector == "span":
                self.set_selector(SpanRelativeLayout)
        self.kv_post_done = True

    def transform_eval(self, x: Any, axis: Any) -> Any:
        custom_transform = axis.get_transform()
        return custom_transform.transform_non_affine(np.array([x]))[0]

    def inv_transform_eval(self, x: Any, axis: Any) -> Any:
        inv_custom_transform = axis.get_transform().inverted()
        return inv_custom_transform.transform_non_affine(np.array([x]))[0]

    def on_current_selector(self, _instance: Any, value: Any, *_args: Any) -> None:
        if self.kv_post_done and selector_widgets_available:
            if value == "rectangle":
                self.set_selector(ResizeRelativeLayout)
            elif value == "lasso":
                self.set_selector(LassoRelativeLayout)
            elif value == "ellipse":
                self.set_selector(EllipseRelativeLayout)
            elif self.current_selector == "span":
                self.set_selector(SpanRelativeLayout)
            elif value == "None":
                if self.selector:
                    Window.unbind(mouse_pos=self.selector.resize_wgt.on_mouse_pos)
                    self.parent.remove_widget(self.selector)
                self.selector = None

    def set_selector(self, selector: Any, *_args: Any) -> None:
        selector_collection = None
        selector_line = None
        callback = None
        callback_clear = None
        if self.selector:
            selector_collection = self.selector.resize_wgt.collection
            selector_line = self.selector.resize_wgt.line
            callback = self.selector.resize_wgt.callback
            callback_clear = self.selector.resize_wgt.callback_clear
            Window.unbind(mouse_pos=self.selector.resize_wgt.on_mouse_pos)
            self.parent.remove_widget(self.selector)

        self.selector = selector(figure_wgt=self, desktop_mode=self.desktop_mode)
        self.selector.resize_wgt.ax = self.axes
        if selector_collection:
            self.set_collection()
        if selector_line:
            self.set_line(selector_line)
        if callback:
            self.set_callback(callback)
        if callback_clear:
            self.set_callback_clear(callback_clear)

        self.parent.add_widget(self.selector)

    def set_collection(self) -> None:
        self.selector.resize_wgt.ax = self.axes
        collections = self.figure.axes[0].collections

        if collections:
            self.selector.resize_wgt.set_collection(collections[0])

    def set_line(self, line: Any) -> None:
        self.selector.resize_wgt.ax = self.axes
        self.selector.resize_wgt.set_line(line)

    def set_callback(self, callback: Any) -> None:
        self.selector.resize_wgt.set_callback(callback)

    def set_callback_clear(self, callback: Any) -> None:
        self.selector.resize_wgt.set_callback_clear(callback)

    def register_lines(self, lines: list[Any]) -> None:
        """register lines method

        Args:
            lines (list): list of matplolib line class

        Return:
            None
        """
        ax = self.figure.axes[0]
        # use sel,axes limit to avoid graph rescale
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()

        # create cross hair cursor
        self.horizontal_line = ax.axhline(y=self.ymin, color="k", lw=0.8, ls="--", visible=False)
        self.vertical_line = ax.axvline(x=self.xmin, color="k", lw=0.8, ls="--", visible=False)

        # register lines
        self.lines = lines

        # cursor text
        self.text = ax.text(1.0, 1.01, "", transform=ax.transAxes, ha="right")

    def set_cross_hair_visible(self, visible: bool) -> None:
        """set curcor visibility

        Args:
            visible (bool): make cursor visble or not

        Return:
            None

        """
        self.horizontal_line.set_visible(visible)
        self.vertical_line.set_visible(visible)
        self.text.set_visible(visible)

    def update_cursor(self) -> None:
        if self.twinx and self.horizontal_line and self.cursor_last_axis:  # noqa: SIM102
            if self.horizontal_line.get_visible() or self.hover_instance:  # noqa: SIM102
                if self.cursor_last_axis == self.figure.axes[1]:
                    if self.hover_instance:
                        if (
                            self.hover_instance.show_cursor
                            and self.x_hover_data is not None
                            and self.y_hover_data is not None
                        ):
                            self.y_hover_data = self.cursor_last_y
                            xy_pos = self.figure.axes[1].transData.transform([(self.x_hover_data, self.y_hover_data)])
                            self.hover_instance.y_hover_pos = float(xy_pos[0][1]) + self.y

                    else:
                        new_y = self.cursor_last_y
                        x = self.vertical_line.get_xdata()
                        trans = self.figure.axes[0].transData.inverted()
                        xy_pos = self.figure.axes[1].transData.transform([(x, new_y)])
                        xdata, ydata = trans.transform_point((xy_pos[0][0], xy_pos[0][1]))
                        self.horizontal_line.set_ydata(
                            [
                                ydata,
                            ]
                        )

    def clear_line_prop(self) -> None:
        """clear attribute line_prop method

        Args:
            None

        Return:
            None

        """
        if self.last_line_prop:
            for key in self.last_line_prop:
                set_line_attr = getattr(self.last_line, "set_" + key)
                set_line_attr(self.last_line_prop[key])
            self.last_line_prop = {}
        self.last_line = None

    def hover(self, event: Any) -> None:
        """hover cursor method (cursor to nearest value)

        Args:
            event: touch kivy event

        Return:
            None

        """

        # if cursor is set -> hover is on
        if self.hover_on:
            # transform kivy x,y touch event to x,y data
            trans = self.figure.axes[0].transData.inverted()
            xdata, ydata = trans.transform_point((event.x - self.pos[0], event.y - self.pos[1]))

            # loop all register lines and find closest x,y data for each valid line
            distance = []
            good_line = []
            good_index = []
            for line in self.lines:
                # get only visible lines
                if line.get_visible():
                    # get line x,y datas
                    self.x_cursor, self.y_cursor = line.get_xydata().T

                    # check if line is not empty
                    if len(self.x_cursor) != 0:
                        # find closest data index from touch (x axis)
                        if self.xsorted:
                            index = min(np.searchsorted(self.x_cursor, xdata), len(self.y_cursor) - 1)

                        else:
                            index = np.argsort(abs(self.x_cursor - xdata))[0]

                        # get x data from index
                        x = self.x_cursor[index]

                        if self.compare_xdata:
                            y = self.y_cursor[index]

                            # get distance between line and touch (in pixels)
                            ax = line.axes
                            # left axis
                            if self.twinx:
                                if ax == self.figure.axes[1]:
                                    # right axis
                                    trans = self.figure.axes[1].transData.inverted()
                                    xdata2, ydata2 = trans.transform_point(
                                        (event.x - self.pos[0], event.y - self.pos[1])
                                    )
                                    xy_pixels_mouse = ax.transData.transform(np.vstack([xdata2, ydata2]).T)
                                else:
                                    # left axis
                                    xy_pixels_mouse = ax.transData.transform([(xdata, ydata)])
                            else:
                                # left axis
                                xy_pixels_mouse = ax.transData.transform([(xdata, ydata)])
                            if np.ma.is_masked(x) or np.ma.is_masked(y) or np.isnan(x) or np.isnan(y):  # type: ignore[no-untyped-call]
                                distance.append(np.nan)
                            else:
                                xy_pixels = ax.transData.transform([(x, ydata)])
                                dx2 = xy_pixels_mouse[0][0] - xy_pixels[0][0]
                                distance.append(abs(dx2))
                        else:
                            # find ydata corresponding to xdata
                            y = self.y_cursor[index]

                            # get distance between line and touch (in pixels)
                            ax = line.axes
                            if self.twinx:
                                if ax == self.figure.axes[1]:
                                    # right axis
                                    trans = self.figure.axes[1].transData.inverted()
                                    xdata2, ydata2 = trans.transform_point(
                                        (event.x - self.pos[0], event.y - self.pos[1])
                                    )
                                    xy_pixels_mouse = ax.transData.transform(np.vstack([xdata2, ydata2]).T)
                                else:
                                    # left axis
                                    xy_pixels_mouse = ax.transData.transform([(xdata, ydata)])
                            else:
                                # left axis
                                xy_pixels_mouse = ax.transData.transform([(xdata, ydata)])
                            if np.ma.is_masked(x) or np.ma.is_masked(y):  # type: ignore[no-untyped-call]
                                distance.append(np.nan)
                            else:
                                xy_pixels = ax.transData.transform([(x, y)])
                                dx2 = (xy_pixels_mouse[0][0] - xy_pixels[0][0]) ** 2
                                dy2 = (xy_pixels_mouse[0][1] - xy_pixels[0][1]) ** 2

                                # store distance
                                if self.pick_radius_axis == "both":
                                    distance.append((dx2 + dy2) ** 0.5)
                                if self.pick_radius_axis == "x":
                                    distance.append(abs(dx2))
                                if self.pick_radius_axis == "y":
                                    distance.append(abs(dy2))

                        # store all best lines and index
                        good_line.append(line)
                        good_index.append(index)

            # case if no good line
            if len(good_line) == 0:
                return

            # if minimum distance if lower than 50 pixels, get line datas with
            # minimum distance
            if np.nanmin(distance) < self.pick_minimum_radius:
                # index of minimum distance
                if self.compare_xdata:
                    if not self.hover_instance or not hasattr(self.hover_instance, "children_list"):
                        return

                    idx_best_list = np.flatnonzero(np.array(distance) == np.nanmin(distance))
                    # get datas from closest line
                    line = good_line[idx_best_list[0]]
                    self.x_cursor, self.y_cursor = line.get_xydata().T
                    x = self.x_cursor[good_index[idx_best_list[0]]]
                    y = self.y_cursor[good_index[idx_best_list[0]]]

                    ax = line.axes
                    xy_pos = ax.transData.transform([(x, y)])
                    self.x_hover_data = x
                    self.y_hover_data = y
                    self.hover_instance.x_hover_pos = float(xy_pos[0][0]) + self.x
                    self.hover_instance.y_hover_pos = float(xy_pos[0][1]) + self.y
                    self.hover_instance.y_touch_pos = float(xy_pixels[0][1]) + self.y

                    if self.first_call_compare_hover:
                        self.hover_instance.show_cursor = True
                    else:
                        self.first_call_compare_hover = True

                    if len(idx_best_list) > 0:
                        available_widget = self.hover_instance.children_list
                        nb_widget = len(available_widget)
                        index_list = list(range(nb_widget))
                        for i, _current_idx_best in enumerate(idx_best_list):
                            if i > nb_widget - 1:
                                break
                            line = good_line[idx_best_list[i]]
                            line_label = line.get_label()
                            if line_label in self.hover_instance.children_names:
                                index = self.hover_instance.children_names.index(line_label)
                                y_cursor = line.get_ydata()
                                y = y_cursor[good_index[idx_best_list[i]]]
                                ax = line.axes

                                xy_pos = ax.transData.transform([(x, y)])
                                pos_y = float(xy_pos[0][1]) + self.y

                                if (
                                    pos_y < self.y + ax.bbox.bounds[1] + ax.bbox.bounds[3]
                                    and pos_y > self.y + ax.bbox.bounds[1]
                                ):
                                    available_widget[index].x_hover_pos = float(xy_pos[0][0]) + self.x
                                    available_widget[index].y_hover_pos = float(xy_pos[0][1]) + self.y
                                    available_widget[index].custom_color = get_color_from_hex(to_hex(line.get_color()))

                                    if self.twinx:
                                        if ax == self.figure.axes[1]:
                                            if self.cursor_yaxis2_formatter:
                                                y = self.cursor_yaxis2_formatter.format_data(y)
                                            else:
                                                y = ax.yaxis.get_major_formatter().format_data_short(y)
                                        else:
                                            if self.cursor_yaxis_formatter:
                                                y = self.cursor_yaxis_formatter.format_data(y)

                                    else:
                                        if self.cursor_yaxis_formatter:
                                            y = self.cursor_yaxis_formatter.format_data(y)
                                        else:
                                            y = ax.yaxis.get_major_formatter().format_data_short(y)
                                    available_widget[index].label_y_value = f"{y}"
                                    available_widget[index].show_widget = True
                                    index_list.remove(index)

                        for ii in index_list:
                            available_widget[ii].show_widget = False

                        if self.cursor_xaxis_formatter:
                            x = self.cursor_xaxis_formatter.format_data(x)
                        else:
                            x = ax.xaxis.get_major_formatter().format_data_short(x)

                        self.hover_instance.label_x_value = f"{x}"

                        if hasattr(self.hover_instance, "overlap_check"):
                            self.hover_instance.overlap_check()

                        self.hover_instance.xmin_line = float(ax.bbox.bounds[0]) + self.x
                        self.hover_instance.xmax_line = float(ax.bbox.bounds[0] + ax.bbox.bounds[2]) + self.x
                        self.hover_instance.ymin_line = float(ax.bbox.bounds[1]) + self.y
                        self.hover_instance.ymax_line = float(ax.bbox.bounds[1] + ax.bbox.bounds[3]) + self.y

                        if (
                            self.hover_instance.x_hover_pos > self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0]
                            or self.hover_instance.x_hover_pos < self.x + ax.bbox.bounds[0]
                            or len(index_list) == nb_widget
                        ):
                            self.hover_instance.hover_outside_bound = True
                        else:
                            self.hover_instance.hover_outside_bound = False

                        return

                else:
                    idx_best = np.nanargmin(distance)

                    # get datas from closest line
                    line = good_line[idx_best]
                    self.x_cursor, self.y_cursor = line.get_xydata().T
                    x = self.x_cursor[good_index[idx_best]]
                    y = self.y_cursor[good_index[idx_best]]

                    if not self.hover_instance:
                        self.set_cross_hair_visible(True)

                    # update the cursor x,y data
                    ax = line.axes
                    self.cursor_last_axis = ax
                    if self.twinx:
                        if ax == self.figure.axes[1]:
                            cur_ylim = self.figure.axes[0].get_ylim()
                            cur_ylim2 = self.figure.axes[1].get_ylim()

                            ratio = (cur_ylim2[1] - cur_ylim2[0]) / (cur_ylim[1] - cur_ylim[0])
                            new_y = (y - cur_ylim2[0]) / ratio + cur_ylim[0]
                            self.horizontal_line.set_ydata(
                                [
                                    new_y,
                                ]
                            )

                            self.cursor_last_y = new_y
                            if self.cursor_yaxis2_formatter and not self.hover_instance:
                                y = self.cursor_yaxis2_formatter.format_data(y)
                            elif not self.hover_instance:
                                y = ax.yaxis.get_major_formatter().format_data_short(y)
                        else:
                            self.horizontal_line.set_ydata(
                                [
                                    y,
                                ]
                            )
                            if self.cursor_yaxis_formatter and not self.hover_instance:
                                y = self.cursor_yaxis_formatter.format_data(y)
                            elif not self.hover_instance:
                                y = ax.yaxis.get_major_formatter().format_data_short(y)
                    else:
                        self.horizontal_line.set_ydata(
                            [
                                y,
                            ]
                        )
                        if self.cursor_yaxis_formatter and not self.hover_instance:
                            y = self.cursor_yaxis_formatter.format_data(y)
                        elif not self.hover_instance:
                            y = ax.yaxis.get_major_formatter().format_data_short(y)
                    self.vertical_line.set_xdata(
                        [
                            x,
                        ]
                    )
                    if self.cursor_xaxis_formatter and not self.hover_instance:
                        x = self.cursor_xaxis_formatter.format_data(x)
                    elif not self.hover_instance:
                        x = ax.xaxis.get_major_formatter().format_data_short(x)

                    # x y label
                    if self.hover_instance:
                        xy_pos = ax.transData.transform([(x, y)])
                        self.x_hover_data = x
                        self.y_hover_data = y
                        self.hover_instance.x_hover_pos = float(xy_pos[0][0]) + self.x
                        self.hover_instance.y_hover_pos = float(xy_pos[0][1]) + self.y
                        self.hover_instance.show_cursor = True

                        if self.twinx:
                            if ax == self.figure.axes[1]:
                                if self.cursor_yaxis2_formatter:
                                    y = self.cursor_yaxis2_formatter.format_data(y)
                                else:
                                    y = ax.yaxis.get_major_formatter().format_data_short(y)
                            else:
                                if self.cursor_yaxis_formatter:
                                    y = self.cursor_yaxis_formatter.format_data(y)
                                else:
                                    y = ax.yaxis.get_major_formatter().format_data_short(y)

                        else:
                            if self.cursor_yaxis_formatter:
                                y = self.cursor_yaxis_formatter.format_data(y)
                            else:
                                y = ax.yaxis.get_major_formatter().format_data_short(y)

                        if self.cursor_xaxis_formatter:
                            x = self.cursor_xaxis_formatter.format_data(x)
                        else:
                            x = ax.xaxis.get_major_formatter().format_data_short(x)

                        self.hover_instance.label_x_value = f"{x}"
                        self.hover_instance.label_y_value = f"{y}"

                        self.hover_instance.xmin_line = float(ax.bbox.bounds[0]) + self.x
                        self.hover_instance.xmax_line = float(ax.bbox.bounds[0] + ax.bbox.bounds[2]) + self.x
                        self.hover_instance.ymin_line = float(ax.bbox.bounds[1]) + self.y
                        self.hover_instance.ymax_line = float(ax.bbox.bounds[1] + ax.bbox.bounds[3]) + self.y

                        self.hover_instance.custom_label = line.get_label()
                        self.hover_instance.custom_color = get_color_from_hex(to_hex(line.get_color()))

                        if (
                            self.hover_instance.x_hover_pos
                            > self.x + self.figure.axes[0].bbox.bounds[2] + self.figure.axes[0].bbox.bounds[0]
                            or self.hover_instance.x_hover_pos < self.x + self.figure.axes[0].bbox.bounds[0]
                            or self.hover_instance.y_hover_pos
                            > self.y + self.figure.axes[0].bbox.bounds[1] + self.figure.axes[0].bbox.bounds[3]
                            or self.hover_instance.y_hover_pos < self.y + self.figure.axes[0].bbox.bounds[1]
                        ):
                            self.hover_instance.hover_outside_bound = True
                        else:
                            self.hover_instance.hover_outside_bound = False

                        if self.highlight_hover:
                            self.myevent.x = event.x - self.pos[0]
                            self.myevent.y = event.y - self.pos[1]
                            self.myevent.inaxes = self.figure.canvas.inaxes(
                                (event.x - self.pos[0], event.y - self.pos[1])
                            )

                            axes = [a for a in self.figure.canvas.figure.get_axes() if a.in_axes(self.myevent)]

                            if not axes or not isinstance(line, mlines.Line2D):
                                if self.last_line:
                                    self.clear_line_prop()
                                    if self.background:
                                        ax.figure.canvas.restore_region(self.background)
                                        # draw (blit method)
                                        ax.figure.canvas.blit(ax.bbox)
                                        ax.figure.canvas.flush_events()
                                        self.background = None

                                return

                            # blit method (always use because same visual effect as draw)
                            if self.background is None:
                                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                            if self.last_line is None:
                                default_alpha = []
                                lines_list = self.lines  # get all register lines
                                for current_line in lines_list:
                                    default_alpha.append(current_line.get_alpha())
                                    current_line.set_alpha(self.highlight_alpha)

                                ax.figure.canvas.draw_idle()
                                ax.figure.canvas.flush_events()
                                self.background_highlight = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                                self.last_line = line
                                for i, current_line in enumerate(lines_list):
                                    current_line.set_alpha(default_alpha[i])
                                    default_alpha[i]

                                if self.highlight_prop:
                                    self.last_line_prop = {}
                                    for key in self.highlight_prop:
                                        # if hasattr(line,key):
                                        line_attr = getattr(line, "get_" + key)
                                        self.last_line_prop.update({key: line_attr()})
                                        set_line_attr = getattr(line, "set_" + key)
                                        set_line_attr(self.highlight_prop[key])
                            elif self.last_line_prop:
                                for key in self.last_line_prop:
                                    set_line_attr = getattr(self.last_line, "set_" + key)
                                    set_line_attr(self.last_line_prop[key])
                                self.hover_instance.custom_color = get_color_from_hex(to_hex(line.get_color()))
                                self.last_line_prop = {}
                                for key in self.highlight_prop:
                                    line_attr = getattr(line, "get_" + key)
                                    self.last_line_prop.update({key: line_attr()})
                                    set_line_attr = getattr(line, "set_" + key)
                                    set_line_attr(self.highlight_prop[key])
                                self.last_line = line

                            ax.figure.canvas.restore_region(self.background_highlight)
                            ax.draw_artist(line)

                            # draw (blit method)
                            ax.figure.canvas.blit(ax.bbox)
                            ax.figure.canvas.flush_events()

                        return
                    self.text.set_text(f"x={x}, y={y}")

                    # blit method (always use because same visual effect as draw)
                    if self.background is None:
                        self.set_cross_hair_visible(False)
                        self.figure.canvas.draw_idle()
                        self.figure.canvas.flush_events()
                        self.background = self.figure.canvas.copy_from_bbox(self.figure.bbox)
                        self.set_cross_hair_visible(True)
                        if self.last_line is not None:
                            self.clear_line_prop()

                    self.figure.canvas.restore_region(self.background)
                    self.figure.axes[0].draw_artist(self.text)

                    self.figure.axes[0].draw_artist(self.horizontal_line)
                    self.figure.axes[0].draw_artist(self.vertical_line)

                    # draw (blit method)
                    self.figure.canvas.blit(self.figure.axes[0].bbox)
                    self.figure.canvas.flush_events()

            # if touch is too far, hide cross hair cursor
            else:
                self.set_cross_hair_visible(False)
                if self.hover_instance:
                    self.hover_instance.x_hover_pos = self.x
                    self.hover_instance.y_hover_pos = self.y
                    self.hover_instance.show_cursor = False
                    self.x_hover_data = None
                    self.y_hover_data = None

                    if self.highlight_hover:
                        self.myevent.x = event.x - self.pos[0]
                        self.myevent.y = event.y - self.pos[1]
                        self.myevent.inaxes = self.figure.canvas.inaxes((event.x - self.pos[0], event.y - self.pos[1]))

                        axes = [a for a in self.figure.canvas.figure.get_axes() if a.in_axes(self.myevent)]

                        if not axes:
                            if self.last_line:
                                self.clear_line_prop()
                                if self.background:
                                    self.figure.canvas.restore_region(self.background)
                                    # draw (blit method)
                                    self.figure.canvas.blit(self.figure.axes[0].bbox)
                                    self.figure.canvas.flush_events()
                                    self.background = None
                            return

    def autoscale(self) -> None:
        if self.disabled:
            return
        ax = self.figure.axes[0]
        ax.relim(visible_only=self.autoscale_visible_only)
        ax.autoscale_view(
            tight=self.autoscale_tight,
            scalex=self.autoscale_axis != "y",
            scaley=self.autoscale_axis != "x",
        )
        ax.autoscale(axis=self.autoscale_axis, tight=self.autoscale_tight)
        if self.twinx:
            ax2 = self.figure.axes[1]
            if self.autoscale_axis != "x":
                ax2.relim(visible_only=self.autoscale_visible_only)
                ax2.autoscale_view(tight=self.autoscale_tight, scalex=False, scaley=True)
                ax2.autoscale(axis="y", tight=self.autoscale_tight)

                self.ymin2, self.ymax2 = ax2.get_ylim()
        ax.figure.canvas.draw_idle()
        ax.figure.canvas.flush_events()
        ax.set_autoscale_on(False)

        self.xmin, self.xmax = ax.get_xlim()
        self.ymin, self.ymax = ax.get_ylim()

    def home(self) -> None:
        """reset data axis

        Return:
            None
        """
        ax = self.figure.axes[0]
        xleft, xright = ax.get_xlim()
        ybottom, ytop = ax.get_ylim()

        # check inverted data
        inverted_x = False
        if xleft > xright:
            inverted_x = True
        inverted_y = False
        if ybottom > ytop:
            inverted_y = True

        if inverted_x:
            ax.set_xlim(right=self.xmin, left=self.xmax)
        else:
            ax.set_xlim(left=self.xmin, right=self.xmax)
        if inverted_y:
            ax.set_ylim(top=self.ymin, bottom=self.ymax)
        else:
            ax.set_ylim(bottom=self.ymin, top=self.ymax)

        if self.twinx:
            ax2 = self.figure.axes[1]
            ybottom2, ytop2 = ax2.get_ylim()
            inverted_y2 = False
            if ybottom2 > ytop2:
                inverted_y2 = True
            if inverted_y2:
                ax2.set_ylim(top=self.ymin2, bottom=self.ymax2)
            else:
                ax2.set_ylim(bottom=self.ymin2, top=self.ymax2)

            self.update_cursor()

        if self.last_line is not None:
            self.clear_line_prop()

        ax.figure.canvas.draw_idle()
        ax.figure.canvas.flush_events()

    def back(self, *_args: Any) -> None:
        """
        Move back up the view lim stack.
        For convenience of being directly connected as a GUI callback, which
        often get passed additional parameters, this method accepts arbitrary
        parameters, but does not use them.
        """
        self._nav_stack.back()
        self.set_history_buttons()
        self._update_view()

    def forward(self, *_args: Any) -> None:
        """
        Move forward in the view lim stack.
        For convenience of being directly connected as a GUI callback, which
        often get passed additional parameters, this method accepts arbitrary
        parameters, but does not use them.
        """
        self._nav_stack.forward()
        self.set_history_buttons()
        self._update_view()

    def push_current(self) -> None:
        """Push the current view limits and position onto the stack."""
        self._nav_stack.push(
            WeakKeyDictionary(
                {
                    ax: (
                        ax._get_view(),
                        # Store both the original and modified positions.
                        (ax.get_position(True).frozen(), ax.get_position().frozen()),
                    )
                    for ax in self.figure.axes
                }
            )
        )
        self.set_history_buttons()

    def update(self) -> None:
        """Reset the Axes stack."""
        self._nav_stack.clear()
        self.set_history_buttons()

    def _update_view(self) -> None:
        """
        Update the viewlim and position from the view and position stack for
        each Axes.
        """
        nav_info = self._nav_stack()
        if nav_info is None:
            return
        # Retrieve all items at once to avoid any risk of GC deleting an Axes
        # while in the middle of the loop below.
        items = list(nav_info.items())
        for ax, (view, (pos_orig, pos_active)) in items:
            ax._set_view(view)
            # Restore both the original and modified positions
            ax._set_position(pos_orig, "original")
            ax._set_position(pos_active, "active")
        self.figure.canvas.draw_idle()
        self.figure.canvas.flush_events()

    def set_history_buttons(self) -> None:
        """Enable or disable the back/forward button."""

    def reset_touch(self) -> None:
        """reset touch

        Return:
            None
        """
        self._touches = []
        self._last_touch_pos = {}

    def _get_scale(self) -> Any:
        """kivy scatter _get_scale method"""
        p1 = Vector(*self.to_parent(0, 0))
        p2 = Vector(*self.to_parent(1, 0))
        scale = p1.distance(p2)

        # XXX float calculation are not accurate, and then, scale can be
        # throwed again even with only the position change. So to
        # prevent anything wrong with scale, just avoid to dispatch it
        # if the scale "visually" didn't change. #947
        # Remove this ugly hack when we'll be Python 3 only.
        if hasattr(self, "_scale_p") and str(scale) == str(self._scale_p):  # type: ignore[has-type]
            return self._scale_p  # type: ignore[has-type]

        self._scale_p = scale
        return scale

    def _set_scale(self, scale: float) -> None:
        """kivy scatter _set_scale method"""
        rescale = scale * 1.0 / self.scale
        self.apply_transform(
            Matrix().scale(rescale, rescale, rescale), post_multiply=True, anchor=self.to_local(*self.center)
        )

    scale = AliasProperty(_get_scale, _set_scale, bind=("x", "y", "transform"))
    """Scale value of the scatter.

    :attr:`scale` is an :class:`~kivy.properties.AliasProperty` and defaults to
    1.0.
    """

    def _draw_bitmap(self) -> None:
        """draw bitmap method. based on kivy scatter method"""
        if self._bitmap is None:
            print("No bitmap!")
            return
        self._img_texture = Texture.create(size=(self.bt_w, self.bt_h))
        self._img_texture.blit_buffer(bytes(self._bitmap), colorfmt="rgba", bufferfmt="ubyte")
        self._img_texture.flip_vertical()

        self.update_hover()
        self.update_selector()

    def transform_with_touch(self, event: Any) -> bool:
        """manage touch behaviour. based on kivy scatter method"""
        # just do a simple one finger drag
        changed = False

        if len(self._touches) == self.translation_touches:
            if self.touch_mode == "pan":
                if self._nav_stack() is None:
                    self.push_current()
                if self.twinx:
                    self.apply_pan_twinx(self.figure.axes[0], self.figure.axes[1], event)
                else:
                    self.apply_pan(self.figure.axes[0], event)

            if (
                self.touch_mode == "pan_x"
                or self.touch_mode == "pan_y"
                or self.touch_mode == "adjust_x"
                or self.touch_mode == "adjust_y"
            ):
                if self._nav_stack() is None:
                    self.push_current()
                if self.twinx:
                    self.apply_pan_twinx(self.figure.axes[0], self.figure.axes[1], event, mode=self.touch_mode)
                else:
                    self.apply_pan(self.figure.axes[0], event, mode=self.touch_mode)

            elif self.touch_mode == "drag_legend":
                if self.legend_instance:
                    self.apply_drag_legend(self.figure.axes[0], event)

            elif self.touch_mode == "zoombox":
                if self._nav_stack() is None:
                    self.push_current()
                _real_x, real_y = event.x - self.pos[0], event.y - self.pos[1]
                # in case x_init is not create
                if not hasattr(self, "x_init"):
                    self.x_init = event.x
                    self.y_init = real_y
                self.draw_box(event, self.x_init, self.y_init, event.x, real_y)

            # mode cursor
            elif self.touch_mode == "cursor":
                self.hover_on = True
                self.hover(event)

            changed = True

        # note: avoid zoom in/out on touch mode zoombox
        if len(self._touches) == 1:  #
            return changed

        # we have more than one touch... list of last known pos
        points = [Vector(self._last_touch_pos[t]) for t in self._touches if t is not event]
        # add current touch last
        points.append(Vector(event.pos))

        # we only want to transform if the touch is part of the two touches
        # farthest apart! So first we find anchor, the point to transform
        # around as another touch farthest away from current touch's pos
        anchor = max(points[:-1], key=lambda p: p.distance(event.pos))

        # now we find the touch farthest away from anchor, if its not the
        # same as touch. Touch is not one of the two touches used to transform
        farthest = max(points, key=anchor.distance)
        if farthest is not points[-1]:
            return changed

        # ok, so we have touch, and anchor, so we can actually compute the
        # transformation
        old_line = Vector(*event.ppos) - anchor
        new_line = Vector(*event.pos) - anchor
        if not old_line.length():  # div by zero
            return changed

        if self.auto_zoom:
            v1 = Vector(0, 10)
            angle = v1.angle(new_line) + 180
            if angle < 0 + self.zoom_angle_detection or angle > 360 - self.zoom_angle_detection:
                self.do_zoom_x = False
                self.do_zoom_y = True
            elif angle > 90 - self.zoom_angle_detection and angle < 90 + self.zoom_angle_detection:
                self.do_zoom_x = True
                self.do_zoom_y = False
            elif angle > 180 - self.zoom_angle_detection and angle < 180 + self.zoom_angle_detection:
                self.do_zoom_x = False
                self.do_zoom_y = True
            elif angle > 270 - self.zoom_angle_detection and angle < 270 + self.zoom_angle_detection:
                self.do_zoom_x = True
                self.do_zoom_y = False
            else:
                self.do_zoom_x = True
                self.do_zoom_y = True

        if self.do_scale:
            scale = old_line.length() / new_line.length()
            new_scale = scale * self.scale
            if new_scale < self.scale_min:
                scale = self.scale_min / self.scale
            elif new_scale > self.scale_max:
                scale = self.scale_max / self.scale

            if self.twinx:
                self.apply_zoom_twinx(scale, self.figure.axes[0], self.figure.axes[1], anchor=anchor, new_line=new_line)
            else:
                self.apply_zoom(scale, self.figure.axes[0], anchor=anchor, new_line=new_line)

            changed = True
        return changed

    def on_motion(self, *args: Any) -> None:
        """Kivy Event to trigger mouse event on motion
        `enter_notify_event`.
        """
        if self._pressed or self.disabled:  # Do not process this event if there's a touch_move
            return
        pos = args[1]
        newcoord = self.to_widget(pos[0], pos[1])
        x = newcoord[0]
        y = newcoord[1]
        inside = self.collide_point(x, y)
        if inside:  # noqa: SIM102
            # will receive all motion events.
            if self.figcanvas and self.hover_instance:
                # avoid in motion if touch is detected
                if len(self._touches) != 0:
                    return
                FakeEventTwinx.x = x
                FakeEventTwinx.y = y
                self.hover(FakeEventTwinx)

    def get_data_xy(self, _x: Any, _y: Any) -> tuple[Any, Any]:
        """manage x y data in navigation bar TODO"""
        return None, None

    def on_touch_down(self, event: Any) -> Optional[bool]:
        """Manage Mouse/touch press"""
        if self.disabled:
            return None

        x, y = event.x, event.y

        if self.collide_point(x, y) and self.figure:
            self._pressed = True
            self.show_compare_cursor = False
            if self.legend_instance:
                select_legend = False
                for current_legend in self.legend_instance:
                    if current_legend.box.collide_point(x, y):
                        select_legend = True
                        self.current_legend = current_legend
                        break
                if select_legend:
                    if self.touch_mode != "drag_legend":
                        return False
                    event.grab(self)
                    self._touches.append(event)
                    self._last_touch_pos[event] = event.pos
                    if len(self._touches) > 1:
                        # new touch, reset background
                        self.background = None

                    return True
                self.current_legend = None

            if event.is_mouse_scrolling:
                if not self.disable_mouse_scrolling:
                    ax = self.figure.axes[0]
                    if self.twinx:
                        ax2 = self.figure.axes[1]
                        self.zoom_factory_twin(event, ax, ax2, base_scale=1.2)
                    else:
                        self.zoom_factory(event, ax, base_scale=1.2)
                return True

            if event.is_double_tap:
                if not self.disable_double_tap and self.touch_mode != "selector":
                    self.home()
                return True

            if self.touch_mode == "cursor":
                self.hover_on = True
                self.hover(event)
            elif self.touch_mode == "zoombox":
                _real_x, real_y = x - self.pos[0], y - self.pos[1]
                self.x_init = x
                self.y_init = real_y
                self.draw_box(event, x, real_y, x, real_y)

            elif self.touch_mode == "minmax":
                self.min_max(event)
            elif self.touch_mode == "selector":
                pass

            event.grab(self)
            self._touches.append(event)
            self._last_touch_pos[event] = event.pos
            if len(self._touches) > 1:
                # new touch, reset background
                self.background = None

            return True

        return False

    def on_touch_move(self, event: Any) -> Optional[bool]:
        """Manage Mouse/touch move while pressed"""
        if self.disabled:
            return None

        x, y = event.x, event.y

        if event.is_double_tap:
            if not self.disable_double_tap and self.touch_mode != "selector":
                self.home()
            return True

        # scale/translate
        if event in self._touches and event.grab_current == self:
            self.transform_with_touch(event)
            self._last_touch_pos[event] = event.pos

        # stop propagating if its within our bounds
        if self.collide_point(x, y):
            return True
        return None

    def on_touch_up(self, event: Any) -> Optional[bool]:
        """Manage Mouse/touch release"""
        if self.disabled:
            return None

        # remove it from our saved touches
        if event in self._touches and event.grab_state:
            event.ungrab(self)
            del self._last_touch_pos[event]
            self._touches.remove(event)
            if (
                self.touch_mode == "pan"
                or self.touch_mode == "zoombox"
                or self.touch_mode == "pan_x"
                or self.touch_mode == "pan_y"
                or self.touch_mode == "adjust_x"
                or self.touch_mode == "adjust_y"
                or self.touch_mode == "minmax"
            ):
                self.push_current()
                if self.interactive_axis:
                    if (
                        self.touch_mode == "pan_x"
                        or self.touch_mode == "pan_y"
                        or self.touch_mode == "adjust_x"
                        or self.touch_mode == "adjust_y"
                    ):
                        self.touch_mode = "pan"
                    self.first_touch_pan = None

                if self.last_line is not None:
                    self.clear_line_prop()

        x, y = event.x, event.y
        if abs(self._box_size[0]) > 1 or abs(self._box_size[1]) > 1 or self.touch_mode == "zoombox":
            self.reset_box()
            if not self.collide_point(x, y) and self.do_update:
                # update axis lim if zoombox is used and touch outside widget
                self.update_lim()
                self.figure.canvas.draw_idle()
                self.figure.canvas.flush_events()
                return True

        # stop propagating if its within our bounds
        if self.collide_point(x, y) and self.figure:
            self._pressed = False

            if self.do_update:
                self.update_lim()

            self.anchor_x = None
            self.anchor_y = None

            self.background = None
            self.show_compare_cursor = True
            self.figure.canvas.draw_idle()
            self.figure.canvas.flush_events()
            if self.last_line is None or self.touch_mode != "cursor":
                self.figure.canvas.draw_idle()
                self.figure.canvas.flush_events()

            return True
        return None

    def apply_zoom(self, scale_factor: Any, ax: Any, anchor: Any = (0, 0), new_line: Any = None) -> None:
        """zoom touch method"""
        if self.touch_mode == "selector":
            return

        x = anchor[0] - self.pos[0]
        y = anchor[1] - self.pos[1]

        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((x + new_line.x, y + new_line.y))

        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()

        scale = ax.get_xscale()
        yscale = ax.get_yscale()

        if scale == "linear":
            old_min = cur_xlim[0]
            old_max = cur_xlim[1]

        else:
            min_ = cur_xlim[0]
            max_ = cur_xlim[1]
            old_min = self.transform_eval(min_, ax.yaxis)
            xdata = self.transform_eval(xdata, ax.yaxis)
            old_max = self.transform_eval(max_, ax.yaxis)

        if yscale == "linear":
            yold_min = cur_ylim[0]
            yold_max = cur_ylim[1]

        else:
            ymin_ = cur_ylim[0]
            ymax_ = cur_ylim[1]
            yold_min = self.transform_eval(ymin_, ax.yaxis)
            ydata = self.transform_eval(ydata, ax.yaxis)
            yold_max = self.transform_eval(ymax_, ax.yaxis)

        new_width = (old_max - old_min) * scale_factor
        new_height = (yold_max - yold_min) * scale_factor

        relx = (old_max - xdata) / (old_max - old_min)
        rely = (yold_max - ydata) / (yold_max - yold_min)

        if self.do_zoom_x:
            if scale == "linear":
                ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * (relx)])
            else:
                new_min = xdata - new_width * (1 - relx)
                new_max = xdata + new_width * (relx)
                try:
                    new_min, new_max = (
                        self.inv_transform_eval(new_min, ax.yaxis),
                        self.inv_transform_eval(new_max, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_min, new_max = min_, max_
                    if new_min <= 0.0 or new_max <= 0.0:  # Limit case
                        new_min, new_max = min_, max_
                ax.set_xlim([new_min, new_max])

        if self.do_zoom_y:
            if yscale == "linear":
                ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * (rely)])
            else:
                new_ymin = ydata - new_height * (1 - rely)
                new_ymax = ydata + new_height * (rely)
                try:
                    new_ymin, new_ymax = (
                        self.inv_transform_eval(new_ymin, ax.yaxis),
                        self.inv_transform_eval(new_ymax, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin, new_ymax = ymin_, ymax_
                    if new_ymin <= 0.0 or new_ymax <= 0.0:  # Limit case
                        new_ymin, new_ymax = ymin_, ymax_
                ax.set_ylim([new_ymin, new_ymax])

        if self.fast_draw:
            # use blit method
            if self.background is None or self.last_line is not None:
                self.background_patch_copy.set_visible(True)
                ax.figure.canvas.draw_idle()
                ax.figure.canvas.flush_events()
                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                self.background_patch_copy.set_visible(False)
                if self.last_line is not None:
                    self.clear_line_prop()
            ax.figure.canvas.restore_region(self.background)

            for line in ax.lines:
                ax.draw_artist(line)
            ax.figure.canvas.blit(ax.bbox)
            ax.figure.canvas.flush_events()

            self.update_hover()
        else:
            ax.figure.canvas.draw_idle()
            ax.figure.canvas.flush_events()

    def apply_zoom_twinx(
        self, scale_factor: Any, ax: Any, ax2: Any, anchor: Any = (0, 0), new_line: Any = None
    ) -> None:
        """twin axis zoom method"""
        if self.touch_mode == "selector":
            return
        x = anchor[0] - self.pos[0]
        y = anchor[1] - self.pos[1]

        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((x + new_line.x, y + new_line.y))
        trans2 = ax2.transData.inverted()
        xdata2, ydata2 = trans2.transform_point((x + new_line.x, y + new_line.y))

        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()
        cur_ylim2 = ax2.get_ylim()

        scale = ax.get_xscale()
        yscale = ax.get_yscale()
        yscale2 = ax2.get_yscale()

        if scale == "linear":
            old_min = cur_xlim[0]
            old_max = cur_xlim[1]

        else:
            min_ = cur_xlim[0]
            max_ = cur_xlim[1]
            old_min = self.transform_eval(min_, ax.yaxis)
            xdata = self.transform_eval(xdata, ax.yaxis)
            old_max = self.transform_eval(max_, ax.yaxis)

        if yscale == "linear":
            yold_min = cur_ylim[0]
            yold_max = cur_ylim[1]

        else:
            ymin_ = cur_ylim[0]
            ymax_ = cur_ylim[1]
            yold_min = self.transform_eval(ymin_, ax.yaxis)
            ydata = self.transform_eval(ydata, ax.yaxis)
            yold_max = self.transform_eval(ymax_, ax.yaxis)

        new_width = (old_max - old_min) * scale_factor
        new_height = (yold_max - yold_min) * scale_factor

        relx = (old_max - xdata) / (old_max - old_min)
        rely = (yold_max - ydata) / (yold_max - yold_min)

        if self.do_zoom_x:
            if scale == "linear":
                ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * (relx)])
            else:
                new_min = xdata - new_width * (1 - relx)
                new_max = xdata + new_width * (relx)
                try:
                    new_min, new_max = (
                        self.inv_transform_eval(new_min, ax.yaxis),
                        self.inv_transform_eval(new_max, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_min, new_max = min_, max_
                    if new_min <= 0.0 or new_max <= 0.0:  # Limit case
                        new_min, new_max = min_, max_
                ax.set_xlim([new_min, new_max])

        if self.do_zoom_y:
            if yscale == "linear":
                ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * (rely)])
            else:
                new_ymin = ydata - new_height * (1 - rely)
                new_ymax = ydata + new_height * (rely)
                try:
                    new_ymin, new_ymax = (
                        self.inv_transform_eval(new_ymin, ax.yaxis),
                        self.inv_transform_eval(new_ymax, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin, new_ymax = ymin_, ymax_
                    if new_ymin <= 0.0 or new_ymax <= 0.0:  # Limit case
                        new_ymin, new_ymax = ymin_, ymax_
                ax.set_ylim([new_ymin, new_ymax])

        if yscale2 == "linear":
            yold2_min = cur_ylim2[0]
            yold2_max = cur_ylim2[1]

        else:
            ymin2_ = cur_ylim2[0]
            ymax2_ = cur_ylim2[1]
            yold2_min = self.transform_eval(ymin2_, ax2.yaxis)
            ydata2 = self.transform_eval(ydata2, ax2.yaxis)
            yold2_max = self.transform_eval(ymax2_, ax2.yaxis)

        new_height2 = (yold2_max - yold2_min) * scale_factor

        rely2 = (yold2_max - ydata2) / (yold2_max - yold2_min)
        if self.do_zoom_y:
            ax2.set_ylim([ydata2 - new_height2 * (1 - rely2), ydata2 + new_height2 * (rely2)])

            if yscale2 == "linear":
                ax2.set_ylim([ydata2 - new_height2 * (1 - rely2), ydata2 + new_height2 * (rely2)])
            else:
                new_ymin2 = ydata2 - new_height2 * (1 - rely2)
                new_ymax2 = ydata2 + new_height2 * (rely2)
                try:
                    new_ymin2, new_ymax2 = (
                        self.inv_transform_eval(new_ymin2, ax2.yaxis),
                        self.inv_transform_eval(new_ymax2, ax2.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin2, new_ymax2 = ymin2_, ymax2_
                    if new_ymin2 <= 0.0 or new_ymax2 <= 0.0:  # Limit case
                        new_ymin2, new_ymax2 = ymin2_, ymax2_
                ax2.set_ylim([new_ymin2, new_ymax2])

        if self.fast_draw:
            # use blit method
            if self.background is None or self.last_line is not None:
                self.background_patch_copy.set_visible(True)
                self.background_ax2_patch_copy.set_visible(True)
                ax.figure.canvas.draw_idle()
                ax.figure.canvas.flush_events()
                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                self.background_patch_copy.set_visible(False)
                self.background_ax2_patch_copy.set_visible(False)
                if self.last_line is not None:
                    self.clear_line_prop()
            ax.figure.canvas.restore_region(self.background)

            for line in ax.lines:
                if line.get_visible():
                    ax.draw_artist(line)
            for line in ax2.lines:
                if line.get_visible():
                    ax2.draw_artist(line)

            ax.figure.canvas.blit(ax.bbox)
            ax.figure.canvas.flush_events()

            self.update_hover()

        else:
            ax.figure.canvas.draw_idle()
            ax.figure.canvas.flush_events()

    def apply_pan(self, ax: Any, event: Any, mode: str = "pan") -> None:
        """pan method"""

        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((event.x - self.pos[0], event.y - self.pos[1]))
        xpress, ypress = trans.transform_point(
            (self._last_touch_pos[event][0] - self.pos[0], self._last_touch_pos[event][1] - self.pos[1])
        )

        scale = ax.get_xscale()
        yscale = ax.get_yscale()

        if scale == "linear":
            dx = xdata - xpress
        else:
            dx = self.transform_eval(xdata, ax.xaxis) - self.transform_eval(xpress, ax.xaxis)

        if yscale == "linear":
            dy = ydata - ypress
        else:
            dy = self.transform_eval(ydata, ax.yaxis) - self.transform_eval(ypress, ax.yaxis)

        xleft, xright = self.figure.axes[0].get_xlim()
        ybottom, ytop = self.figure.axes[0].get_ylim()

        # check inverted data
        inverted_x = False
        if xleft > xright:
            inverted_x = True
            cur_xlim = (xright, xleft)
        else:
            cur_xlim = (xleft, xright)
        inverted_y = False
        if ybottom > ytop:
            inverted_y = True
            cur_ylim = (ytop, ybottom)
        else:
            cur_ylim = (ybottom, ytop)

        if self.interactive_axis and self.touch_mode == "pan" and self.first_touch_pan != "pan":
            if (ydata < cur_ylim[0] and not inverted_y) or (ydata > cur_ylim[1] and inverted_y):
                left_anchor_zone = (cur_xlim[1] - cur_xlim[0]) * 0.2 + cur_xlim[0]
                right_anchor_zone = (cur_xlim[1] - cur_xlim[0]) * 0.8 + cur_xlim[0]
                mode = "adjust_x" if xdata < left_anchor_zone or xdata > right_anchor_zone else "pan_x"
                self.touch_mode = mode
            elif (xdata < cur_xlim[0] and not inverted_x) or (xdata > cur_xlim[1] and inverted_x):
                bottom_anchor_zone = (cur_ylim[1] - cur_ylim[0]) * 0.2 + cur_ylim[0]
                top_anchor_zone = (cur_ylim[1] - cur_ylim[0]) * 0.8 + cur_ylim[0]
                mode = "adjust_y" if ydata < bottom_anchor_zone or ydata > top_anchor_zone else "pan_y"
                self.touch_mode = mode
            else:
                self.touch_mode = "pan"

        if mode != "pan_y" and mode != "adjust_y":
            if mode == "adjust_x":
                if self.anchor_x is None:
                    midpoint = (cur_xlim[1] + cur_xlim[0]) / 2
                    if xdata > midpoint:
                        self.anchor_x = "left"
                    else:
                        self.anchor_x = "right"
                if self.anchor_x == "left":
                    if xdata > cur_xlim[0]:
                        if scale == "linear":
                            cur_xlim -= dx
                        else:
                            try:
                                cur_xlim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_xlim = cur_xlim  # Keep previous limits
                        if inverted_x:
                            ax.set_xlim(cur_xlim[1], None)
                        else:
                            ax.set_xlim(None, cur_xlim[1])
                else:
                    if xdata < cur_xlim[1]:
                        if scale == "linear":
                            cur_xlim -= dx
                        else:
                            try:
                                cur_xlim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_xlim = cur_xlim  # Keep previous limits
                        if inverted_x:
                            ax.set_xlim(None, cur_xlim[0])
                        else:
                            ax.set_xlim(cur_xlim[0], None)
            else:
                if scale == "linear":
                    cur_xlim -= dx
                else:
                    try:
                        cur_xlim = [  # type: ignore[assignment]
                            self.inv_transform_eval((self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis),
                            self.inv_transform_eval((self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis),
                        ]
                    except (ValueError, OverflowError):
                        cur_xlim = cur_xlim  # Keep previous limits
                if inverted_x:
                    ax.set_xlim(cur_xlim[1], cur_xlim[0])
                else:
                    ax.set_xlim(cur_xlim)

        if mode != "pan_x" and mode != "adjust_x":
            if mode == "adjust_y":
                if self.anchor_y is None:
                    midpoint = (cur_ylim[1] + cur_ylim[0]) / 2
                    if ydata > midpoint:
                        self.anchor_y = "top"
                    else:
                        self.anchor_y = "bottom"

                if self.anchor_y == "top":
                    if ydata > cur_ylim[0]:
                        if yscale == "linear":
                            cur_ylim -= dy

                        else:
                            try:
                                cur_ylim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim = cur_ylim  # Keep previous limits

                        if inverted_y:
                            ax.set_ylim(cur_ylim[1], None)
                        else:
                            ax.set_ylim(None, cur_ylim[1])
                else:
                    if ydata < cur_ylim[1]:
                        if yscale == "linear":
                            cur_ylim -= dy

                        else:
                            try:
                                cur_ylim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim = cur_ylim  # Keep previous limits
                        if inverted_y:
                            ax.set_ylim(None, cur_ylim[0])
                        else:
                            ax.set_ylim(cur_ylim[0], None)
            else:
                if yscale == "linear":
                    cur_ylim -= dy

                else:
                    try:
                        cur_ylim = [  # type: ignore[assignment]
                            self.inv_transform_eval((self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis),
                            self.inv_transform_eval((self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis),
                        ]
                    except (ValueError, OverflowError):
                        cur_ylim = cur_ylim  # Keep previous limits
                if inverted_y:
                    ax.set_ylim(cur_ylim[1], cur_ylim[0])
                else:
                    ax.set_ylim(cur_ylim)

        if self.first_touch_pan is None:
            self.first_touch_pan = self.touch_mode

        if self.fast_draw:
            # use blit method
            if self.background is None or self.last_line is not None:
                self.background_patch_copy.set_visible(True)
                ax.figure.canvas.draw_idle()
                ax.figure.canvas.flush_events()
                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                self.background_patch_copy.set_visible(False)
                if self.last_line is not None:
                    self.clear_line_prop()
            ax.figure.canvas.restore_region(self.background)

            for line in ax.lines:
                ax.draw_artist(line)

            ax.figure.canvas.blit(ax.bbox)
            ax.figure.canvas.flush_events()

            self.update_hover()

        else:
            ax.figure.canvas.draw_idle()
            ax.figure.canvas.flush_events()

    def apply_pan_twinx(self, ax: Any, ax2: Any, event: Any, mode: str = "pan") -> None:
        """twin axis pan method"""
        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((event.x - self.pos[0], event.y - self.pos[1]))
        xpress, ypress = trans.transform_point(
            (self._last_touch_pos[event][0] - self.pos[0], self._last_touch_pos[event][1] - self.pos[1])
        )

        scale = ax.get_xscale()
        yscale = ax.get_yscale()
        yscale2 = ax2.get_yscale()

        update_cursor = False

        if scale == "linear":
            dx = xdata - xpress
        else:
            dx = self.transform_eval(xdata, ax.xaxis) - self.transform_eval(xpress, ax.xaxis)

        if yscale == "linear":
            dy = ydata - ypress
        else:
            dy = self.transform_eval(ydata, ax.yaxis) - self.transform_eval(ypress, ax.yaxis)

        xleft, xright = ax.get_xlim()
        ybottom, ytop = ax.get_ylim()
        ybottom2, ytop2 = ax2.get_ylim()

        # check inverted data
        inverted_x = False
        if xleft > xright:
            inverted_x = True
            cur_xlim = (xright, xleft)
        else:
            cur_xlim = (xleft, xright)
        inverted_y = False
        if ybottom > ytop:
            inverted_y = True
            cur_ylim = (ytop, ybottom)
        else:
            cur_ylim = (ybottom, ytop)
        inverted_y2 = False
        if ybottom2 > ytop2:
            inverted_y2 = True
            cur_ylim2 = (ytop2, ybottom2)
        else:
            cur_ylim2 = (ybottom2, ytop2)

        ratio = (cur_ylim2[1] - cur_ylim2[0]) / (cur_ylim[1] - cur_ylim[0])
        ydata2 = ydata * ratio + cur_ylim2[0]
        ypress2 = ypress * ratio + cur_ylim2[0]

        if yscale2 == "linear":
            dy2 = ydata2 - ypress2
        else:
            dy2 = self.transform_eval(ydata2, ax2.yaxis) - self.transform_eval(ypress2, ax2.yaxis)

        if self.interactive_axis and self.touch_mode == "pan" and self.first_touch_pan != "pan":
            if (ydata < cur_ylim[0] and not inverted_y) or (ydata > cur_ylim[1] and inverted_y):
                left_anchor_zone = (cur_xlim[1] - cur_xlim[0]) * 0.2 + cur_xlim[0]
                right_anchor_zone = (cur_xlim[1] - cur_xlim[0]) * 0.8 + cur_xlim[0]
                mode = "adjust_x" if xdata < left_anchor_zone or xdata > right_anchor_zone else "pan_x"
                self.touch_mode = mode
            elif (
                (xdata < cur_xlim[0] and not inverted_y)
                or (xdata > cur_xlim[1] and inverted_y)
                or (xdata > cur_xlim[1] and not inverted_y)
                or (xdata < cur_xlim[0] and inverted_y)
            ):
                bottom_anchor_zone = (cur_ylim[1] - cur_ylim[0]) * 0.2 + cur_ylim[0]
                top_anchor_zone = (cur_ylim[1] - cur_ylim[0]) * 0.8 + cur_ylim[0]
                mode = "adjust_y" if ydata < bottom_anchor_zone or ydata > top_anchor_zone else "pan_y"
                self.touch_mode = mode

            else:
                self.touch_mode = "pan"

        if mode != "pan_y" and mode != "adjust_y":
            if mode == "adjust_x":
                if self.anchor_x is None:
                    midpoint = (cur_xlim[1] + cur_xlim[0]) / 2
                    if xdata > midpoint:
                        self.anchor_x = "left"
                    else:
                        self.anchor_x = "right"
                if self.anchor_x == "left":
                    if xdata > cur_xlim[0]:
                        if scale == "linear":
                            cur_xlim -= dx
                        else:
                            try:
                                cur_xlim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_xlim = cur_xlim  # Keep previous limits
                        if inverted_x:
                            ax.set_xlim(cur_xlim[1], None)
                        else:
                            ax.set_xlim(None, cur_xlim[1])

                else:
                    if xdata < cur_xlim[1]:
                        if scale == "linear":
                            cur_xlim -= dx
                        else:
                            try:
                                cur_xlim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_xlim = cur_xlim  # Keep previous limits
                        if inverted_x:
                            ax.set_xlim(None, cur_xlim[0])
                        else:
                            ax.set_xlim(cur_xlim[0], None)

            else:
                if scale == "linear":
                    cur_xlim -= dx
                else:
                    try:
                        cur_xlim = [  # type: ignore[assignment]
                            self.inv_transform_eval((self.transform_eval(cur_xlim[0], ax.xaxis) - dx), ax.xaxis),
                            self.inv_transform_eval((self.transform_eval(cur_xlim[1], ax.xaxis) - dx), ax.xaxis),
                        ]
                    except (ValueError, OverflowError):
                        cur_xlim = cur_xlim  # Keep previous limits
                if inverted_x:
                    ax.set_xlim(cur_xlim[1], cur_xlim[0])
                else:
                    ax.set_xlim(cur_xlim)

        if mode != "pan_x" and mode != "adjust_x":
            if mode == "adjust_y":
                trans_ax2 = ax2.transData.inverted()
                xdata_ax2, ydata_ax2 = trans_ax2.transform_point((event.x - self.pos[0], event.y - self.pos[1]))
                if self.anchor_y is None:
                    midpoint_x = (cur_xlim[1] + cur_xlim[0]) / 2
                    midpoint_ax1 = (cur_ylim[1] + cur_ylim[0]) / 2
                    midpoint_ax2 = (cur_ylim2[1] + cur_ylim2[0]) / 2
                    if (xdata > midpoint_x and not inverted_x) or (xdata < midpoint_x and inverted_x):
                        ax_anchor = "right"
                    else:
                        ax_anchor = "left"

                    if ax_anchor == "left":
                        if ydata > midpoint_ax1:
                            self.anchor_y = "top_left"
                        else:
                            self.anchor_y = "bottom_left"
                    else:
                        if ydata_ax2 > midpoint_ax2:
                            self.anchor_y = "top_right"
                        else:
                            self.anchor_y = "bottom_right"
                if self.anchor_y == "top_left":
                    if ydata > cur_ylim[0]:
                        if yscale == "linear":
                            cur_ylim -= dy

                        else:
                            try:
                                cur_ylim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim = cur_ylim  # Keep previous limits
                        if inverted_y:
                            ax.set_ylim(cur_ylim[1], None)
                        else:
                            ax.set_ylim(None, cur_ylim[1])

                        update_cursor = True

                elif self.anchor_y == "top_right":
                    if ydata_ax2 > cur_ylim2[0]:
                        if yscale2 == "linear":
                            cur_ylim2 -= dy2

                        else:
                            try:
                                cur_ylim2 = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim2[0], ax2.yaxis) - dy2), ax2.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim2[1], ax2.yaxis) - dy2), ax2.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim2 = cur_ylim2  # Keep previous limits

                        if inverted_y2:
                            ax2.set_ylim(cur_ylim2[1], None)
                        else:
                            ax2.set_ylim(None, cur_ylim2[1])

                        update_cursor = True

                elif self.anchor_y == "bottom_left":
                    if ydata < cur_ylim[1]:
                        if yscale == "linear":
                            cur_ylim -= dy

                        else:
                            try:
                                cur_ylim = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim = cur_ylim  # Keep previous limits
                        if inverted_y:
                            ax.set_ylim(None, cur_ylim[0])
                        else:
                            ax.set_ylim(cur_ylim[0], None)

                        update_cursor = True
                else:
                    if ydata_ax2 < cur_ylim2[1]:
                        if yscale2 == "linear":
                            cur_ylim2 -= dy2

                        else:
                            try:
                                cur_ylim2 = [  # type: ignore[assignment]
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim2[0], ax2.yaxis) - dy2), ax2.yaxis
                                    ),
                                    self.inv_transform_eval(
                                        (self.transform_eval(cur_ylim2[1], ax2.yaxis) - dy2), ax2.yaxis
                                    ),
                                ]
                            except (ValueError, OverflowError):
                                cur_ylim2 = cur_ylim2  # Keep previous limits
                        if inverted_y2:
                            ax2.set_ylim(None, cur_ylim2[0])
                        else:
                            ax2.set_ylim(cur_ylim2[0], None)

                        update_cursor = True
            else:
                if yscale == "linear":
                    cur_ylim -= dy

                else:
                    try:
                        cur_ylim = [  # type: ignore[assignment]
                            self.inv_transform_eval((self.transform_eval(cur_ylim[0], ax.yaxis) - dy), ax.yaxis),
                            self.inv_transform_eval((self.transform_eval(cur_ylim[1], ax.yaxis) - dy), ax.yaxis),
                        ]
                    except (ValueError, OverflowError):
                        cur_ylim = cur_ylim  # Keep previous limits

                if yscale2 == "linear":
                    cur_ylim2 -= dy2

                else:
                    try:
                        cur_ylim2 = [  # type: ignore[assignment]
                            self.inv_transform_eval((self.transform_eval(cur_ylim2[0], ax2.yaxis) - dy2), ax2.yaxis),
                            self.inv_transform_eval((self.transform_eval(cur_ylim2[1], ax2.yaxis) - dy2), ax2.yaxis),
                        ]
                    except (ValueError, OverflowError):
                        cur_ylim2 = cur_ylim2  # Keep previous limits
                if inverted_y:
                    ax.set_ylim(cur_ylim[1], cur_ylim[0])
                else:
                    ax.set_ylim(cur_ylim)
                if inverted_y2:
                    ax2.set_ylim(cur_ylim2[1], cur_ylim2[0])
                else:
                    ax2.set_ylim(cur_ylim2)

        if self.first_touch_pan is None:
            self.first_touch_pan = self.touch_mode

        if update_cursor:
            self.update_cursor()

        if self.fast_draw:
            # use blit method
            if self.background is None or self.last_line is not None:
                self.background_patch_copy.set_visible(True)
                self.background_ax2_patch_copy.set_visible(True)
                ax.figure.canvas.draw_idle()
                ax.figure.canvas.flush_events()
                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                self.background_patch_copy.set_visible(False)
                self.background_ax2_patch_copy.set_visible(False)
                if self.last_line is not None:
                    self.clear_line_prop()
            ax.figure.canvas.restore_region(self.background)

            for line in ax.lines:
                if line.get_visible():
                    ax.draw_artist(line)
            for line in ax2.lines:
                if line.get_visible():
                    ax2.draw_artist(line)

            ax.figure.canvas.blit(ax.bbox)
            ax.figure.canvas.flush_events()

            self.update_hover()

        else:
            ax.figure.canvas.draw_idle()
            ax.figure.canvas.flush_events()

    def update_hover(self) -> None:
        """update hover on fast draw (if exist)"""
        if self.hover_instance:
            if self.compare_xdata and self.hover_instance:
                if (self.touch_mode != "cursor" or len(self._touches) > 1) and not self.show_compare_cursor:
                    self.hover_instance.hover_outside_bound = True

                elif self.show_compare_cursor and self.touch_mode == "cursor":
                    self.show_compare_cursor = False
                else:
                    self.hover_instance.hover_outside_bound = True

            # update hover pos if needed
            elif self.hover_instance.show_cursor and self.x_hover_data is not None and self.y_hover_data is not None:
                if self.cursor_last_axis:
                    xy_pos = self.cursor_last_axis.transData.transform([(self.x_hover_data, self.y_hover_data)])
                else:
                    xy_pos = self.figure.axes[0].transData.transform([(self.x_hover_data, self.y_hover_data)])
                self.hover_instance.x_hover_pos = float(xy_pos[0][0]) + self.x
                self.hover_instance.y_hover_pos = float(xy_pos[0][1]) + self.y

                self.hover_instance.xmin_line = float(self.figure.axes[0].bbox.bounds[0]) + self.x
                self.hover_instance.xmax_line = (
                    float(self.figure.axes[0].bbox.bounds[0] + self.figure.axes[0].bbox.bounds[2]) + self.x
                )
                self.hover_instance.ymin_line = float(self.figure.axes[0].bbox.bounds[1]) + self.y
                self.hover_instance.ymax_line = (
                    float(self.figure.axes[0].bbox.bounds[1] + self.figure.axes[0].bbox.bounds[3]) + self.y
                )

                if (
                    self.hover_instance.x_hover_pos
                    > self.x + self.figure.axes[0].bbox.bounds[2] + self.figure.axes[0].bbox.bounds[0]
                    or self.hover_instance.x_hover_pos < self.x + self.figure.axes[0].bbox.bounds[0]
                    or self.hover_instance.y_hover_pos
                    > self.y + self.figure.axes[0].bbox.bounds[1] + self.figure.axes[0].bbox.bounds[3]
                    or self.hover_instance.y_hover_pos < self.y + self.figure.axes[0].bbox.bounds[1]
                ):
                    self.hover_instance.hover_outside_bound = True
                else:
                    self.hover_instance.hover_outside_bound = False

    def update_selector(self, *args: Any) -> None:
        """update selector on fast draw (if exist)"""
        if self.selector and self.selector.resize_wgt.verts and (len(args) != 0 or self.touch_mode != "selector"):
            # update selector pos if needed
            resize_wgt = self.selector.resize_wgt

            if hasattr(resize_wgt, "shapes"):
                # lasso widget or ellipse
                if resize_wgt.shapes:
                    if hasattr(resize_wgt.shapes[0], "radius_x"):
                        # ellipse widget
                        xy_pos = resize_wgt.ax.transData.transform([(resize_wgt.verts[1][0], resize_wgt.verts[1][1])])
                        new_pos = resize_wgt.to_widget(*(float(xy_pos[0][0]), float(xy_pos[0][1])))
                        pos0 = new_pos[0] + self.x
                        pos1 = new_pos[1] + self.y

                        xy_pos2 = resize_wgt.ax.transData.transform([(resize_wgt.verts[2][0], resize_wgt.verts[2][1])])
                        new_pos2 = resize_wgt.to_widget(*(float(xy_pos2[0][0]), float(xy_pos2[0][1])))
                        pos0_2 = new_pos2[0] + self.x
                        pos1_2 = new_pos2[1] + self.y

                        current_shape = resize_wgt.shapes[0]
                        dataxy1 = current_shape.selection_point_inst.points
                        dataxy2 = current_shape.selection_point_inst2.points

                        # note: the 2 first points are the same in current_shape.points
                        pos0_old = dataxy1[0]
                        pos1_old = dataxy1[1]

                        pos0_2_old = dataxy2[0]
                        pos1_2_old = dataxy2[1]

                        old_length = np.sqrt((pos0_2_old - pos0_old) ** 2 + (pos1_2_old - pos1_old) ** 2)
                        new_length = np.sqrt((pos0_2 - pos0) ** 2 + (pos1_2 - pos1) ** 2)

                        scale = float(new_length / old_length)

                        xy_pos3 = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][0], resize_wgt.verts[0][1])])
                        new_pos3 = resize_wgt.to_widget(*(float(xy_pos3[0][0]), float(xy_pos3[0][1])))
                        pos0_c = new_pos3[0] + self.x
                        pos1_c = new_pos3[1] + self.y

                        for s in resize_wgt.shapes:
                            s.rescale(scale)

                        for s in resize_wgt.shapes:
                            s.translate(pos=(pos0_c, pos1_c))

                        xmin, xmax, ymin, ymax = resize_wgt.shapes[0].get_min_max()
                    else:
                        # lasso widget
                        xy_pos = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][0], resize_wgt.verts[0][1])])
                        new_pos = resize_wgt.to_widget(*(float(xy_pos[0][0]), float(xy_pos[0][1])))
                        pos0 = new_pos[0] + self.x
                        pos1 = new_pos[1] + self.y

                        xy_pos2 = resize_wgt.ax.transData.transform([(resize_wgt.verts[1][0], resize_wgt.verts[1][1])])
                        new_pos2 = resize_wgt.to_widget(*(float(xy_pos2[0][0]), float(xy_pos2[0][1])))
                        pos0_2 = new_pos2[0] + self.x
                        pos1_2 = new_pos2[1] + self.y

                        current_shape = resize_wgt.shapes[0]
                        dataxy = np.array(current_shape.points).reshape(-1, 2)

                        # note: the 2 first points are the same in current_shape.points
                        pos0_old = dataxy[1][0]
                        pos1_old = dataxy[1][1]

                        pos0_2_old = dataxy[2][0]
                        pos1_2_old = dataxy[2][1]

                        old_length = np.sqrt((pos0_2_old - pos0_old) ** 2 + (pos1_2_old - pos1_old) ** 2)
                        new_length = np.sqrt((pos0_2 - pos0) ** 2 + (pos1_2 - pos1) ** 2)

                        scale = new_length / old_length

                        for s in resize_wgt.shapes:
                            s.rescale(scale)

                        for s in resize_wgt.shapes:
                            s.translate(pos=(pos0, pos1))

                        xmax, ymax = dataxy.max(axis=0)
                        xmin, ymin = dataxy.min(axis=0)

                    if self.collide_point(*resize_wgt.to_window(xmin, ymin)) and self.collide_point(
                        *resize_wgt.to_window(xmax, ymax)
                    ):
                        resize_wgt.opacity = 1
                    else:
                        resize_wgt.opacity = 0

            elif self.selector.resize_wgt.verts and (len(args) != 0 or self.touch_mode != "selector"):
                resize_wgt = self.selector.resize_wgt
                if not (resize_wgt.size[0] > 1 and resize_wgt.size[1] > 1):
                    return

                # rectangle or spann selector
                if hasattr(resize_wgt, "span_orientation"):
                    # span selector
                    if resize_wgt.span_orientation == "vertical":
                        xy_pos = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][0], resize_wgt.verts[0][1])])
                        new_pos = resize_wgt.to_widget(*(float(xy_pos[0][0]), float(xy_pos[0][1])))
                        resize_wgt.pos[0] = new_pos[0] + self.x

                        top_bound = float(self.y + resize_wgt.ax.bbox.bounds[3] + resize_wgt.ax.bbox.bounds[1])
                        bottom_bound = float(self.y + resize_wgt.ax.bbox.bounds[1])
                        resize_wgt.pos[1] = bottom_bound - self.y

                        # recalcul size
                        xy_pos2 = resize_wgt.ax.transData.transform([(resize_wgt.verts[3][0], resize_wgt.verts[3][1])])
                        resize_wgt.size[0] = float(xy_pos2[0][0] - xy_pos[0][0])
                        resize_wgt.size[1] = top_bound - bottom_bound

                    elif resize_wgt.span_orientation == "horizontal":
                        xy_pos = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][0], resize_wgt.verts[0][1])])
                        new_pos = resize_wgt.to_widget(*(float(xy_pos[0][0]), float(xy_pos[0][1])))
                        left_bound = float(self.x + resize_wgt.ax.bbox.bounds[0])
                        right_bound = float(self.x + resize_wgt.ax.bbox.bounds[2] + resize_wgt.ax.bbox.bounds[0])

                        width = right_bound - left_bound

                        left_bound, right_bound = resize_wgt.to_widget(left_bound, right_bound)

                        resize_wgt.pos[0] = left_bound
                        resize_wgt.pos[1] = new_pos[1] + self.y

                        # recalcul size
                        xy_pos2 = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][1], resize_wgt.verts[1][1])])
                        resize_wgt.size[0] = width
                        resize_wgt.size[1] = float(xy_pos2[0][1] - xy_pos[0][1])

                else:
                    # rectangle selector

                    # update all selector pts
                    # recalcul pos
                    xy_pos = resize_wgt.ax.transData.transform([(resize_wgt.verts[0][0], resize_wgt.verts[0][1])])
                    new_pos = resize_wgt.to_widget(*(float(xy_pos[0][0]), float(xy_pos[0][1])))
                    resize_wgt.pos[0] = new_pos[0] + self.x
                    resize_wgt.pos[1] = new_pos[1] + self.y

                    # recalcul size
                    xy_pos2 = resize_wgt.ax.transData.transform([(resize_wgt.verts[2][0], resize_wgt.verts[2][1])])
                    resize_wgt.size[0] = float(xy_pos2[0][0] - xy_pos[0][0])
                    resize_wgt.size[1] = float(xy_pos2[0][1] - xy_pos[0][1])

                if self.collide_point(
                    *resize_wgt.to_window(resize_wgt.pos[0], resize_wgt.pos[1])
                ) and self.collide_point(
                    *resize_wgt.to_window(
                        resize_wgt.pos[0] + resize_wgt.size[0], resize_wgt.pos[1] + resize_wgt.size[1]
                    )
                ):
                    resize_wgt.opacity = 1
                else:
                    resize_wgt.opacity = 0

    def min_max(self, event: Any) -> None:
        """manage min/max touch mode"""
        ax = self.figure.axes[0]  # left axis
        xlabelbottom = ax.xaxis._major_tick_kw.get("tick1On")
        ylabelleft = ax.yaxis._major_tick_kw.get("tick1On")
        ylabelright = ax.yaxis._major_tick_kw.get("tick2On")

        if (
            xlabelbottom
            and event.x > self.x + ax.bbox.bounds[0]
            and event.x < self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0]
            and event.y < self.y + ax.bbox.bounds[1]
        ):
            right_lim = self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0]
            left_lim = self.x + ax.bbox.bounds[0]
            left_anchor_zone = (right_lim - left_lim) * 0.2 + left_lim
            right_anchor_zone = (right_lim - left_lim) * 0.8 + left_lim

            if (event.x < left_anchor_zone or event.x > right_anchor_zone) and self.text_instance:  # noqa: SIM102
                if not self.text_instance.show_text:
                    midpoint = ((self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0]) + (self.x + ax.bbox.bounds[0])) / 2
                    if event.x < midpoint:
                        anchor = "left"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[0])
                        self.text_instance.y_text_pos = (
                            float(self.y + ax.bbox.bounds[1]) - self.text_instance.text_height
                        )
                        self.text_instance.offset_text = False
                    else:
                        anchor = "right"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0])
                        self.text_instance.y_text_pos = (
                            float(self.y + ax.bbox.bounds[1]) - self.text_instance.text_height
                        )
                        self.text_instance.offset_text = True

                    self.text_instance.current_axis = ax
                    self.text_instance.kind = {"axis": "x", "anchor": anchor}

                    self.text_instance.show_text = True
                    return

        elif (
            ylabelleft
            and event.x < self.x + ax.bbox.bounds[0]
            and event.y < self.y + ax.bbox.bounds[1] + ax.bbox.bounds[3]
            and event.y > self.y + ax.bbox.bounds[1]
        ):
            top_lim = self.y + ax.bbox.bounds[3] + ax.bbox.bounds[1]
            bottom_lim = self.y + ax.bbox.bounds[1]
            bottom_anchor_zone = (top_lim - bottom_lim) * 0.2 + bottom_lim
            top_anchor_zone = (top_lim - bottom_lim) * 0.8 + bottom_lim

            if (event.y < bottom_anchor_zone or event.y > top_anchor_zone) and self.text_instance:  # noqa: SIM102
                if not self.text_instance.show_text:
                    midpoint = ((self.y + ax.bbox.bounds[3] + ax.bbox.bounds[1]) + (self.y + ax.bbox.bounds[1])) / 2
                    if event.y > midpoint:
                        anchor = "top"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[0]) - dp(40)
                        self.text_instance.y_text_pos = (
                            float(self.y + ax.bbox.bounds[1] + ax.bbox.bounds[3]) - self.text_instance.text_height
                        )
                        self.text_instance.offset_text = False
                    else:
                        anchor = "bottom"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[0]) - dp(40)
                        self.text_instance.y_text_pos = float(self.y + ax.bbox.bounds[1]) - dp(6)
                        self.text_instance.offset_text = False
                    self.text_instance.current_axis = ax
                    self.text_instance.kind = {"axis": "y", "anchor": anchor}

                    self.text_instance.show_text = True
                    return

        elif (
            ylabelright
            and event.x > self.x + ax.bbox.bounds[2] + ax.bbox.bounds[0]
            and event.y < self.y + ax.bbox.bounds[1] + ax.bbox.bounds[3]
            and event.y > self.y + ax.bbox.bounds[1]
        ):
            top_lim = self.y + ax.bbox.bounds[3] + ax.bbox.bounds[1]
            bottom_lim = self.y + ax.bbox.bounds[1]
            bottom_anchor_zone = (top_lim - bottom_lim) * 0.2 + bottom_lim
            top_anchor_zone = (top_lim - bottom_lim) * 0.8 + bottom_lim

            if (event.y < bottom_anchor_zone or event.y > top_anchor_zone) and self.text_instance:  # noqa: SIM102
                if not self.text_instance.show_text:
                    midpoint = ((self.y + ax.bbox.bounds[3] + ax.bbox.bounds[1]) + (self.y + ax.bbox.bounds[1])) / 2
                    if event.y > midpoint:
                        anchor = "top"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[0] + ax.bbox.bounds[2]) + dp(40)
                        self.text_instance.y_text_pos = (
                            float(self.y + ax.bbox.bounds[1] + ax.bbox.bounds[3]) - self.text_instance.text_height
                        )
                        self.text_instance.offset_text = True
                    else:
                        anchor = "bottom"
                        self.text_instance.x_text_pos = float(self.x + ax.bbox.bounds[0] + ax.bbox.bounds[2]) + dp(40)
                        self.text_instance.y_text_pos = float(self.y + ax.bbox.bounds[1]) - dp(6)
                        self.text_instance.offset_text = True
                    self.text_instance.current_axis = self.figure.axes[1]  # left axis
                    self.text_instance.kind = {"axis": "y", "anchor": anchor}

                    self.text_instance.show_text = True
                    return

    def apply_drag_legend(self, ax: Any, event: Any) -> None:
        """drag legend method"""

        dx = event.x - self._last_touch_pos[event][0]
        if not self.legend_do_scroll_x:
            dx = 0
        dy = event.y - self._last_touch_pos[event][1]
        if not self.legend_do_scroll_y:
            dy = 0
        legend = None
        if self.current_legend:
            legend = self.current_legend.legend_instance if self.current_legend.legend_instance else ax.get_legend()
        if legend is not None:
            bbox = legend.get_window_extent()
            legend_x = bbox.xmin
            legend_y = bbox.ymin

            loc_in_canvas = legend_x + dx, legend_y + dy
            loc_in_norm_axes = legend.parent.transAxes.inverted().transform_point(loc_in_canvas)
            legend._loc = tuple(loc_in_norm_axes)

            # use blit method
            if self.background is None or self.last_line is not None:
                legend.set_visible(False)
                ax.figure.canvas.draw_idle()
                ax.figure.canvas.flush_events()
                self.background = ax.figure.canvas.copy_from_bbox(ax.figure.bbox)
                legend.set_visible(True)
                if self.last_line is not None:
                    self.clear_line_prop()
            ax.figure.canvas.restore_region(self.background)

            ax.draw_artist(legend)

            ax.figure.canvas.blit(ax.bbox)
            ax.figure.canvas.flush_events()

            self.current_legend.update_size()

    def zoom_factory(self, event: Any, ax: Any, base_scale: float = 1.1) -> None:
        """zoom with scrolling mouse method"""

        newcoord = self.to_widget(event.x, event.y, relative=True)
        x = newcoord[0]
        y = newcoord[1]

        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((x, y))

        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()

        scale = ax.get_xscale()
        yscale = ax.get_yscale()

        if scale == "linear":
            old_min = cur_xlim[0]
            old_max = cur_xlim[1]

        else:
            min_ = cur_xlim[0]
            max_ = cur_xlim[1]
            old_min = self.transform_eval(min_, ax.yaxis)
            xdata = self.transform_eval(xdata, ax.yaxis)
            old_max = self.transform_eval(max_, ax.yaxis)

        if yscale == "linear":
            yold_min = cur_ylim[0]
            yold_max = cur_ylim[1]

        else:
            ymin_ = cur_ylim[0]
            ymax_ = cur_ylim[1]
            yold_min = self.transform_eval(ymin_, ax.yaxis)
            ydata = self.transform_eval(ydata, ax.yaxis)
            yold_max = self.transform_eval(ymax_, ax.yaxis)

        if event.button == "scrolldown":
            # deal with zoom in
            scale_factor = 1 / base_scale
        elif event.button == "scrollup":
            # deal with zoom out
            scale_factor = base_scale
        else:
            # deal with something that should never happen
            scale_factor = 1
            print(event.button)

        new_width = (old_max - old_min) * scale_factor
        new_height = (yold_max - yold_min) * scale_factor

        relx = (old_max - xdata) / (old_max - old_min)
        rely = (yold_max - ydata) / (yold_max - yold_min)

        if self.do_zoom_x:
            if scale == "linear":
                ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * (relx)])
            else:
                new_min = xdata - new_width * (1 - relx)
                new_max = xdata + new_width * (relx)
                try:
                    new_min, new_max = (
                        self.inv_transform_eval(new_min, ax.yaxis),
                        self.inv_transform_eval(new_max, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_min, new_max = min_, max_
                    if new_min <= 0.0 or new_max <= 0.0:  # Limit case
                        new_min, new_max = min_, max_
                ax.set_xlim([new_min, new_max])

        if self.do_zoom_y:
            if yscale == "linear":
                ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * (rely)])
            else:
                new_ymin = ydata - new_height * (1 - rely)
                new_ymax = ydata + new_height * (rely)
                try:
                    new_ymin, new_ymax = (
                        self.inv_transform_eval(new_ymin, ax.yaxis),
                        self.inv_transform_eval(new_ymax, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin, new_ymax = ymin_, ymax_
                    if new_ymin <= 0.0 or new_ymax <= 0.0:  # Limit case
                        new_ymin, new_ymax = ymin_, ymax_
                ax.set_ylim([new_ymin, new_ymax])

        if self.last_line is not None:
            self.clear_line_prop()

        ax.figure.canvas.draw_idle()
        ax.figure.canvas.flush_events()

    def zoom_factory_twin(self, event: Any, ax: Any, ax2: Any, base_scale: float = 2.0) -> None:
        """twin axis zoom method from scroll mouse"""
        x, y = event.x, event.y
        cur_xlim = ax.get_xlim()
        cur_ylim = ax.get_ylim()

        cur_ylim2 = ax2.get_ylim()

        trans = ax.transData.inverted()
        xdata, ydata = trans.transform_point((x, y))
        trans2 = ax2.transData.inverted()
        xdata2, ydata2 = trans2.transform_point((x, y))

        scale = ax.get_xscale()
        yscale = ax.get_yscale()
        yscale2 = ax2.get_yscale()

        if scale == "linear":
            old_min = cur_xlim[0]
            old_max = cur_xlim[1]

        else:
            min_ = cur_xlim[0]
            max_ = cur_xlim[1]
            old_min = self.transform_eval(min_, ax.yaxis)
            xdata = self.transform_eval(xdata, ax.yaxis)
            old_max = self.transform_eval(max_, ax.yaxis)

        if yscale == "linear":
            yold_min = cur_ylim[0]
            yold_max = cur_ylim[1]

        else:
            ymin_ = cur_ylim[0]
            ymax_ = cur_ylim[1]
            yold_min = self.transform_eval(ymin_, ax.yaxis)
            ydata = self.transform_eval(ydata, ax.yaxis)
            yold_max = self.transform_eval(ymax_, ax.yaxis)

        if event.button == "scrolldown":
            # deal with zoom in
            scale_factor = 1 / base_scale
        elif event.button == "scrollup":
            # deal with zoom out
            scale_factor = base_scale
        else:
            # deal with something that should never happen
            scale_factor = 1
            print(event.button)

        new_width = (old_max - old_min) * scale_factor
        new_height = (yold_max - yold_min) * scale_factor

        relx = (old_max - xdata) / (old_max - old_min)
        rely = (yold_max - ydata) / (yold_max - yold_min)

        if self.do_zoom_x:
            if scale == "linear":
                ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * (relx)])
            else:
                new_min = xdata - new_width * (1 - relx)
                new_max = xdata + new_width * (relx)
                try:
                    new_min, new_max = (
                        self.inv_transform_eval(new_min, ax.yaxis),
                        self.inv_transform_eval(new_max, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_min, new_max = min_, max_
                    if new_min <= 0.0 or new_max <= 0.0:  # Limit case
                        new_min, new_max = min_, max_
                ax.set_xlim([new_min, new_max])

        if self.do_zoom_y:
            if yscale == "linear":
                ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * (rely)])
            else:
                new_ymin = ydata - new_height * (1 - rely)
                new_ymax = ydata + new_height * (rely)
                try:
                    new_ymin, new_ymax = (
                        self.inv_transform_eval(new_ymin, ax.yaxis),
                        self.inv_transform_eval(new_ymax, ax.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin, new_ymax = ymin_, ymax_
                    if new_ymin <= 0.0 or new_ymax <= 0.0:  # Limit case
                        new_ymin, new_ymax = ymin_, ymax_
                ax.set_ylim([new_ymin, new_ymax])

        if yscale2 == "linear":
            yold2_min = cur_ylim2[0]
            yold2_max = cur_ylim2[1]

        else:
            ymin2_ = cur_ylim2[0]
            ymax2_ = cur_ylim2[1]
            yold2_min = self.transform_eval(ymin2_, ax2.yaxis)
            ydata2 = self.transform_eval(ydata2, ax2.yaxis)
            yold2_max = self.transform_eval(ymax2_, ax2.yaxis)

        new_height2 = (yold2_max - yold2_min) * scale_factor

        rely2 = (yold2_max - ydata2) / (yold2_max - yold2_min)
        if self.do_zoom_y:
            ax2.set_ylim([ydata2 - new_height2 * (1 - rely2), ydata2 + new_height2 * (rely2)])

            if yscale2 == "linear":
                ax2.set_ylim([ydata2 - new_height2 * (1 - rely2), ydata2 + new_height2 * (rely2)])
            else:
                new_ymin2 = ydata2 - new_height2 * (1 - rely2)
                new_ymax2 = ydata2 + new_height2 * (rely2)
                try:
                    new_ymin2, new_ymax2 = (
                        self.inv_transform_eval(new_ymin2, ax2.yaxis),
                        self.inv_transform_eval(new_ymax2, ax2.yaxis),
                    )
                except OverflowError:  # Limit case
                    new_ymin2, new_ymax2 = ymin2_, ymax2_
                    if new_ymin2 <= 0.0 or new_ymax2 <= 0.0:  # Limit case
                        new_ymin2, new_ymax2 = ymin2_, ymax2_
                ax2.set_ylim([new_ymin2, new_ymax2])

        if self.last_line is not None:
            self.clear_line_prop()

        ax.figure.canvas.draw_idle()
        ax.figure.canvas.flush_events()

    def _on_size(self, _o: Any, size: Any) -> None:
        """_onsize method"""
        if self.figure is None:
            return
        # Create a new, correctly sized bitmap
        self._width, self._height = size
        self._isDrawn = False

        if self._width <= 1 or self._height <= 1:
            return

        dpival = self.figure.dpi
        winch = self._width / dpival
        hinch = self._height / dpival
        self.figure.set_size_inches(winch, hinch)

        s = "resize_event"
        event = ResizeEvent(s, self.figcanvas)
        self.figcanvas.callbacks.process(s, event)
        self.figcanvas.draw_idle()

        self.figcanvas.draw()
        if self.legend_instance:
            for current_legend in self.legend_instance:
                current_legend.update_size()
        if self.hover_instance:
            self.hover_instance.figwidth = self.width
            self.hover_instance.figheight = self.height
            self.hover_instance.figx = self.x
            self.hover_instance.figy = self.y
        if self.selector and self.selector.resize_wgt.verts:
            # update selector next frame to have correct position
            Clock.schedule_once(self.update_selector)

    def update_lim(self) -> None:
        """update axis lim if zoombox is used"""
        ax = self.figure.axes[0]
        ax2 = self.figure.axes[1]
        self.do_update = False

        # check if inverted axis
        xleft, xright = ax.get_xlim()
        ybottom, ytop = ax.get_ylim()
        ybottom2, ytop2 = ax2.get_ylim()

        # check inverted data
        inverted_x = False
        if xleft > xright:
            inverted_x = True
        else:
            pass
        inverted_y = False
        if ybottom > ytop:
            inverted_y = True
            cur_ylim = (ytop, ybottom)
        else:
            cur_ylim = (ybottom, ytop)
        inverted_y2 = False
        if ybottom2 > ytop2:
            inverted_y2 = True
            cur_ylim2 = (ytop2, ybottom2)
        else:
            cur_ylim2 = (ybottom2, ytop2)

        range_old = cur_ylim[1] - cur_ylim[0]
        range_old2 = cur_ylim2[1] - cur_ylim2[0]

        ymin2 = (min(self.y0_box, self.y1_box) - cur_ylim[0]) / range_old * range_old2 + cur_ylim2[0]  # type: ignore[call-overload]
        ymax2 = (max(self.y0_box, self.y1_box) - cur_ylim[0]) / range_old * range_old2 + cur_ylim2[0]  # type: ignore[call-overload]

        if inverted_x:
            ax.set_xlim(right=min(self.x0_box, self.x1_box), left=max(self.x0_box, self.x1_box))  # type: ignore[call-overload]
        else:
            ax.set_xlim(left=min(self.x0_box, self.x1_box), right=max(self.x0_box, self.x1_box))  # type: ignore[call-overload]
        if inverted_y:
            ax.set_ylim(top=min(self.y0_box, self.y1_box), bottom=max(self.y0_box, self.y1_box))  # type: ignore[call-overload]
        else:
            ax.set_ylim(bottom=min(self.y0_box, self.y1_box), top=max(self.y0_box, self.y1_box))  # type: ignore[call-overload]
        if inverted_y2:
            ax2.set_ylim(top=ymin2, bottom=ymax2)
        else:
            ax2.set_ylim(bottom=ymin2, top=ymax2)

    def reset_box(self) -> None:
        """reset zoombox and apply zoombox limit if zoombox option if selected"""
        if min(abs(self._box_size[0]), abs(self._box_size[1])) > self.minzoom:
            trans = self.figure.axes[0].transData.inverted()
            self.x0_box, self.y0_box = trans.transform_point(
                (self._box_pos[0] - self.pos[0], self._box_pos[1] - self.pos[1])
            )
            self.x1_box, self.y1_box = trans.transform_point(
                (self._box_size[0] + self._box_pos[0] - self.pos[0], self._box_size[1] + self._box_pos[1] - self.pos[1])
            )
            self.do_update = True

        self._box_size = 0, 0
        self._box_pos = 0, 0
        self._alpha_box = 0

        self._pos_x_rect_hor = 0
        self._pos_y_rect_hor = 0
        self._pos_x_rect_ver = 0
        self._pos_y_rect_ver = 0
        self._alpha_hor = 0
        self._alpha_ver = 0
        self.invert_rect_hor = False
        self.invert_rect_ver = False

    def draw_box(self, event: Any, x0: Any, y0: Any, x1: Any, y1: Any) -> None:
        """Draw zoombox method

        Args:
            event: touch kivy event
            x0: x coordonnate init
            x1: y coordonnate of move touch
            y0: y coordonnate init
            y1: x coordonnate of move touch

        Return:
            None
        """
        pos_x, pos_y = self.pos
        # Kivy coords
        y0 = pos_y + y0
        y1 = pos_y + y1

        if abs(y1 - y0) > dp(5) or abs(x1 - x0) > dp(5):
            self._alpha_box = 0.3
            self._alpha_rect = 0

        trans = self.figure.axes[0].transData.inverted()
        xdata, ydata = trans.transform_point((event.x - pos_x, event.y - pos_y))

        xleft, xright = self.figure.axes[0].get_xlim()
        ybottom, ytop = self.figure.axes[0].get_ylim()

        xmax = max(xleft, xright)
        xmin = min(xleft, xright)
        ymax = max(ybottom, ytop)
        ymin = min(ybottom, ytop)

        # check inverted data
        inverted_x = False
        if xleft > xright:
            inverted_x = True
        inverted_y = False
        if ybottom > ytop:
            inverted_y = True

        x0data, y0data = trans.transform_point((x0 - pos_x, y0 - pos_y))
        if x0data > xmax or x0data < xmin or y0data > ymax or y0data < ymin:
            return

        if xdata < xmin:
            x1_min = self.figure.axes[0].transData.transform([(xmin, ymin)])
            if (x1 < x0 and not inverted_x) or (x1 > x0 and inverted_x):
                x1 = x1_min[0][0] + pos_x
            else:
                x0 = x1_min[0][0]

        if xdata > xmax:
            x0_max = self.figure.axes[0].transData.transform([(xmax, ymin)])
            if (x1 > x0 and not inverted_x) or (x1 < x0 and inverted_x):
                x1 = x0_max[0][0] + pos_x
            else:
                x0 = x0_max[0][0]

        if ydata < ymin:
            y1_min = self.figure.axes[0].transData.transform([(xmin, ymin)])
            if (y1 < y0 and not inverted_y) or (y1 > y0 and inverted_y):
                y1 = y1_min[0][1] + pos_y
            else:
                y0 = y1_min[0][1] + pos_y

        if ydata > ymax:
            y0_max = self.figure.axes[0].transData.transform([(xmax, ymax)])
            if (y1 > y0 and not inverted_y) or (y1 < y0 and inverted_y):
                y1 = y0_max[0][1] + pos_y
            else:
                y0 = y0_max[0][1] + pos_y

        if abs(x1 - x0) < dp(20) and abs(y1 - y0) > self.minzoom:
            self.pos_x_rect_ver = x0
            self.pos_y_rect_ver = y0

            x1_min = self.figure.axes[0].transData.transform([(xmin, ymin)])
            x0 = x1_min[0][0] + pos_x

            x0_max = self.figure.axes[0].transData.transform([(xmax, ymin)])
            x1 = x0_max[0][0] + pos_x

            self._alpha_ver = 1
            self._alpha_hor = 0

        elif abs(y1 - y0) < dp(20) and abs(x1 - x0) > self.minzoom:
            self.pos_x_rect_hor = x0
            self.pos_y_rect_hor = y0

            y1_min = self.figure.axes[0].transData.transform([(xmin, ymin)])
            y0 = y1_min[0][1] + pos_y

            y0_max = self.figure.axes[0].transData.transform([(xmax, ymax)])
            y1 = y0_max[0][1] + pos_y

            self._alpha_hor = 1
            self._alpha_ver = 0

        else:
            self._alpha_hor = 0
            self._alpha_ver = 0

        if x1 > x0:
            self.invert_rect_ver = False
        else:
            self.invert_rect_ver = True
        if y1 > y0:
            self.invert_rect_hor = False
        else:
            self.invert_rect_hor = True

        self._box_pos = x0, y0
        self._box_size = x1 - x0, y1 - y0


class _FigureCanvas(FigureCanvasAgg):
    """Internal AGG Canvas"""

    def __init__(self, figure: Any, widget: Any, *args: Any, **kwargs: Any) -> None:
        self.widget = widget
        super().__init__(figure, *args, **kwargs)

    def draw(self) -> None:
        """
        Render the figure using agg.
        """
        super().draw()  # type: ignore[no-untyped-call]
        agg = self.get_renderer()  # type: ignore[no-untyped-call]
        w, h = agg.width, agg.height
        self._isDrawn = True

        self.widget.bt_w = w
        self.widget.bt_h = h
        self.widget._bitmap = agg.buffer_rgba()
        self.widget._draw_bitmap()

    def blit(self, _bbox: Any = None) -> None:
        """
        Render the figure using agg (blit method).
        """
        agg = self.get_renderer()  # type: ignore[no-untyped-call]
        w, h = agg.width, agg.height
        self.widget._bitmap = agg.buffer_rgba()
        self.widget.bt_w = w
        self.widget.bt_h = h
        self.widget._draw_bitmap()


class FakeEventTwinx:
    x: Any = None
    y: Any = None


from kivy.factory import Factory  # noqa: E402

Factory.register("MatplotFigureTwinx", MatplotFigureTwinx)

Builder.load_string("""
<MatplotFigureTwinx>
    canvas:
        Color:
            rgba: (1, 1, 1, 1)
        Rectangle:
            pos: self.pos
            size: self.size
            texture: self._img_texture
        Color:
            rgba: 0, 0, 1, self._alpha_box
        BorderImage:
            source: 'border.png'
            pos: self._box_pos
            size: self._box_size
            border:
                dp(1) if root.invert_rect_hor else -dp(1), \
                dp(1) if root.invert_rect_ver else -dp(1), \
                dp(1) if root.invert_rect_hor else -dp(1), \
                dp(1) if root.invert_rect_ver else -dp(1)

    canvas.after:
        #horizontal rectangle left
		Color:
			rgba:0, 0, 0, self._alpha_hor
		Line:
			width: dp(1)
			rectangle:
				(self.pos_x_rect_hor+dp(1) if root.invert_rect_ver \
                 else self.pos_x_rect_hor-dp(4),self.pos_y_rect_hor-dp(20), dp(4),dp(40))

        #horizontal rectangle right
		Color:
			rgba:0, 0, 0, self._alpha_hor
		Line:
			width: dp(1)
			rectangle:
				(self.pos_x_rect_hor-dp(4)+self._box_size[0] if root.invert_rect_ver \
                 else self.pos_x_rect_hor+dp(1)+self._box_size[0], self.pos_y_rect_hor-dp(20), dp(4),dp(40))

        #vertical rectangle bottom
		Color:
			rgba:0, 0, 0, self._alpha_ver
		Line:
			width: dp(1)
			rectangle:
				(self.pos_x_rect_ver-dp(20),self.pos_y_rect_ver+dp(1) if root.invert_rect_hor else \
                 self.pos_y_rect_ver-dp(4), dp(40),dp(4))

        #vertical rectangle top
		Color:
			rgba:0, 0, 0, self._alpha_ver
		Line:
			width: dp(1)
			rectangle:
				(self.pos_x_rect_ver-dp(20),self.pos_y_rect_ver-dp(4)+self._box_size[1] \
                 if root.invert_rect_hor else self.pos_y_rect_ver+dp(1)+self._box_size[1], \
                 dp(40),dp(4))
        """)


class StaticMatplotFigureTwinx(MatplotFigureTwinx):
    """Read-only variant of MatplotFigureTwinx — all touch interaction disabled."""

    def on_touch_down(self, _event: Any) -> Optional[bool]:
        return False

    def on_touch_move(self, _event: Any) -> Optional[bool]:
        return False

    def on_touch_up(self, _event: Any) -> Optional[bool]:
        return False
