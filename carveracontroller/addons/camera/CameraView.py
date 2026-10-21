"""Camera frame display with host-side brightness, contrast and gamma."""

import logging
from io import BytesIO

from kivy.animation import Animation
from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, PopMatrix, PushMatrix, Rectangle, RenderContext, Rotate
from kivy.metrics import dp
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.widget import Widget

from carveracontroller.ui.theme import get_theme

ADJUST_MIN = 0.2
ADJUST_MAX = 3.0
ADJUST_DEFAULT = 1.0

_FRAGMENT_SHADER = """
$HEADER$
uniform float brightness;
uniform float contrast;
uniform float gamma;
void main(void) {
    vec4 frame = texture2D(texture0, tex_coord0);
    vec3 rgb = frame.rgb * brightness;
    rgb = (rgb - 0.5) * contrast + 0.5;
    rgb = clamp(rgb, 0.0, 1.0);
    rgb = pow(rgb, vec3(1.0 / max(gamma, 0.01)));
    gl_FragColor = vec4(clamp(rgb, 0.0, 1.0), frame.a) * frag_color;
}
"""

logger = logging.getLogger(__name__)

_SPINNER_RADIUS = dp(18)
_SPINNER_WIDTH = dp(3)


class CameraReconnectSpinner(Widget):
    """Dim the camera view and spin an arc while the stream is reconnecting."""

    active = BooleanProperty(False)
    angle = NumericProperty(0)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            self._dim = Color(0, 0, 0, 0)
            self._shade = Rectangle(pos=self.pos, size=self.size)
        with self.canvas:
            self._track_color = Color(*get_theme().text[:3], 0)
            self._track = Line(width=_SPINNER_WIDTH)
            PushMatrix()
            self._rotate = Rotate(angle=0, origin=self.center)
            self._arc_color = Color(*get_theme().text[:3], 0)
            self._arc = Line(width=_SPINNER_WIDTH, cap="round")
            PopMatrix()
        self._animation = None
        self.bind(pos=self._redraw, size=self._redraw, angle=self._redraw)
        self.bind(active=self._on_active)
        self._redraw()

    def _on_active(self, *_args):
        if self._animation is not None:
            self._animation.cancel(self)
            self._animation = None
        if self.active:
            self.angle = 0
            self._animation = Animation(angle=360, duration=0.9, t="linear")
            self._animation.repeat = True
            self._animation.start(self)
        else:
            self.angle = 0
        self._redraw()

    def _redraw(self, *_args):
        shown = bool(self.active)
        dim = get_theme().overlay
        self._dim.rgba = [dim[0], dim[1], dim[2], 0.45 if shown else 0.0]
        self._shade.pos = self.pos
        self._shade.size = self.size
        self._track_color.a = 0.35 if shown else 0
        self._arc_color.a = 1 if shown else 0
        self._rotate.angle = self.angle
        self._rotate.origin = self.center
        center_x, center_y = self.center
        self._track.circle = (center_x, center_y, _SPINNER_RADIUS)
        self._arc.circle = (center_x, center_y, _SPINNER_RADIUS, 0, 280)


class CameraView(Widget):
    """Letterboxes the latest camera frame and grades it through a shader.

    The stream carries no sensor exposure control, so brightness, contrast and
    gamma are applied on the host and cannot recover fully clipped highlights.
    """

    texture = ObjectProperty(None, allownone=True)
    brightness = NumericProperty(ADJUST_DEFAULT)
    contrast = NumericProperty(ADJUST_DEFAULT)
    gamma = NumericProperty(ADJUST_DEFAULT)

    def __init__(self, **kwargs):
        self.canvas = RenderContext(use_parent_projection=True, use_parent_modelview=True)
        self.canvas.shader.fs = _FRAGMENT_SHADER
        super().__init__(**kwargs)
        with self.canvas:
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self._update_uniforms()
        self.bind(
            pos=self._layout_frame,
            size=self._layout_frame,
            texture=self._layout_frame,
            brightness=self._update_uniforms,
            contrast=self._update_uniforms,
            gamma=self._update_uniforms,
        )

    def show_frame(self, jpeg):
        """Decode one JPEG frame, dropping partial or garbled ones."""
        try:
            texture = CoreImage(BytesIO(jpeg), ext="jpg").texture
        except Exception as exc:
            logger.warning("Camera frame decode failed: %s", exc)
            return
        texture.mag_filter = "linear"
        texture.min_filter = "linear"
        self.texture = texture

    def _update_uniforms(self, *args):
        self.canvas["brightness"] = float(self.brightness)
        self.canvas["contrast"] = float(self.contrast)
        self.canvas["gamma"] = float(self.gamma)
        self.canvas.ask_update()

    def _layout_frame(self, *args):
        """Fit the frame to its own aspect ratio so it is never distorted."""
        self._rect.texture = self.texture
        frame_width, frame_height = self.texture.size if self.texture else (0, 0)
        width, height = self.size
        if not (frame_width and frame_height and width and height):
            self._rect.size = self.size
            self._rect.pos = self.pos
            return
        scale = min(width / float(frame_width), height / float(frame_height))
        fitted_width, fitted_height = frame_width * scale, frame_height * scale
        self._rect.size = (fitted_width, fitted_height)
        self._rect.pos = (self.x + (width - fitted_width) / 2.0, self.y + (height - fitted_height) / 2.0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_up(touch)
