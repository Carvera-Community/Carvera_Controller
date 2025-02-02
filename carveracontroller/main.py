import os
import quicklz
import struct

# import os
# os.environ["KIVY_METRICS_DENSITY"] = '1'

import gettext
import locale
from kivy.lang import Observable
from os.path import dirname, join
# os.environ['KIVY_GL_DEBUG'] = '1'

from kivy.utils import platform

import sys
import time
import datetime
import threading
import logging

from carveracontroller.addons.probing.ProbingPopup import ProbingPopup, ProbeGcodeGenerator
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants


class Lang(Observable):
    observers = []
    lang = None

    def __init__(self, defaultlang):
        super(Lang, self).__init__()
        self.ugettext = None
        self.lang = defaultlang
        self.switch_lang(self.lang)

    def _(self, text):
        return self.ugettext(text)

    def fbind(self, name, func, args, **kwargs):
        if name == "_":
            self.observers.append((func, args, kwargs))
        else:
            return super(Lang, self).fbind(name, func, *args, **kwargs)

    def funbind(self, name, func, args, **kwargs):
        if name == "_":
            key = (func, args, kwargs)
            if key in self.observers:
                self.observers.remove(key)
        else:
            return super(Lang, self).funbind(name, func, *args, **kwargs)

    def switch_lang(self, lang):
        # get the right locales directory, and instanciate a gettext
        locale_dir = join(dirname(__file__), 'locales')
        locales = None
        try:
            locales = gettext.translation(lang, locale_dir, languages=[lang])
        except:
            pass
        if locales == None:
            locales = gettext.NullTranslations()
        self.ugettext = locales.gettext
        self.lang = lang

        # update all the kv rules attached to this text
        for func, largs, kwargs in self.observers:
            func(largs, None, None)


import json
import re
import tempfile
from kivy.app import App
from kivy.clock import Clock
from kivy.uix.widget import Widget
from kivy.uix.button import Button
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.relativelayout import RelativeLayout
from kivy.uix.settings import SettingsWithSidebar, SettingItem
from kivy.uix.stencilview import StencilView
from kivy.uix.slider import Slider
from kivy.uix.dropdown import DropDown
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.modalview import ModalView
from kivy.properties import StringProperty
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior
from kivy.uix.label import Label
from kivy.properties import BooleanProperty
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.properties import ObjectProperty, NumericProperty, ListProperty
from kivy.config import Config
from kivy.metrics import Metrics

from serial.tools.list_ports import comports
from functools import partial
from .WIFIStream import MachineDetector
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.resources import resource_add_path
from kivy.network.urlrequest import UrlRequest
import webbrowser
from pathlib import Path

# import os
import shutil
import string
import subprocess

from . import Utils
from kivy.config import ConfigParser
from .CNC import CNC
from .GcodeViewer import GCodeViewer
from .Controller import Controller, NOT_CONNECTED, STATECOLOR, STATECOLORDEF, \
    LOAD_DIR, LOAD_MV, LOAD_RM, LOAD_MKDIR, LOAD_WIFI, LOAD_CONN_WIFI, CONN_USB, CONN_WIFI, SEND_FILE
from .__version__ import __version__


def load_halt_translations(tr: Lang):
    """Loads the appropriate language translation"""
    HALT_REASON = {
        # Just need to unlock the mahchine
        1: tr._("Halt Manually"),
        2: tr._("Home Fail"),
        3: tr._("Probe Fail"),
        4: tr._("Calibrate Fail"),
        5: tr._("ATC Home Fail"),
        6: tr._("ATC Invalid Tool Number"),
        7: tr._("ATC Drop Tool Fail"),
        8: tr._("ATC Position Occupied"),
        9: tr._("Spindle Overheated"),
        10: tr._("Soft Limit Triggered"),
        11: tr._("Cover opened when playing"),
        12: tr._("Wireless probe dead or not set"),
        13: tr._("Emergency stop button pressed"),
        # Need to reset the machine
        21: tr._("Hard Limit Triggered, reset needed"),
        22: tr._("X Axis Motor Error, reset needed"),
        23: tr._("Y Axis Motor Error, reset needed"),
        24: tr._("Z Axis Motor Error, reset needed"),
        25: tr._("Spindle Stall, reset needed"),
        26: tr._("SD card read fail, reset needed"),
        # Need to power off/on the machine
        41: tr._("Spindle Alarm, power off/on needed"),
    }
    return HALT_REASON


def init_lang():
    # init language
    default_lang = 'en'
    if Config.has_option('carvera', 'language'):
        default_lang = Config.get('carvera', 'language')
    else:
        try:
            default_locale = locale.getdefaultlocale()
            if default_locale != None:
                for lang_key in LANGS.keys():
                    if default_locale[0][0:2] in lang_key:
                        default_lang = lang_key
                        break
        except:
            pass

    return default_lang


def is_android():
    return 'ANDROID_ARGUMENT' in os.environ or 'ANDROID_PRIVATE' in os.environ or 'ANDROID_APP_PATH' in os.environ


def app_base_path():
    """
    The base path should be used for reference for any bundled assets.
    This should be done via __file__ since this will work in situations
    where the application is both frozen in pyinstaller, and when run normally
    """
    return os.path.abspath(os.path.dirname(__file__))


def register_fonts(base_path):
    """
    To support both frozen and normal execution of the application font locations
    should be registered
    """
    arialuni_location = os.path.abspath(os.path.join(os.path.dirname(__file__), "ARIALUNI.ttf"))
    LabelBase.register(name='ARIALUNI', fn_regular=arialuni_location)


def register_images(base_path):
    """
    To support both frozen and normal execution of the application image locations
    should be registered
    """
    icons_path = os.path.join(base_path)
    resource_add_path(icons_path)


class GcodePlaySlider(Slider):
    def on_touch_down(self, touch):
        if self.disabled:
            return
        released = super(GcodePlaySlider, self).on_touch_down(touch)
        if released and self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance / 1000)
            return True
        return released

    def on_touch_move(self, touch):
        if self.disabled:
            return
        released = super(GcodePlaySlider, self).on_touch_move(touch)
        if self.collide_point(*touch.pos):
            app = App.get_running_app()
            app.root.gcode_viewer.set_pos_by_distance(self.value * app.root.gcode_viewer_distance / 1000)
            # float_number = self.value * app.root.selected_file_line_count / 1000
            # app.root.gcode_viewer.set_distance_by_lineidx(int(float_number), float_number - int(float_number))
            return True
        return released


class FloatBox(FloatLayout):
    touch_interval = 0

    def on_touch_down(self, touch):
        if super(FloatBox, self).on_touch_down(touch):
            return True

        if self.collide_point(*touch.pos) and not self.gcode_ctl_bar.collide_point(*touch.pos):
            if ('button' in touch.profile and touch.button == 'left') or not 'button' in touch.profile:
                self.touch_interval = time.time()

    def on_touch_up(self, touch):
        if super(FloatBox, self).on_touch_up(touch):
            return True

        app = App.get_running_app()
        if self.collide_point(*touch.pos) and not self.gcode_ctl_bar.collide_point(*touch.pos):
            if ('button' in touch.profile and touch.button == 'left') or not 'button' in touch.profile:
                if time.time() - self.touch_interval < MAX_TOUCH_INTERVAL:
                    app.show_gcode_ctl_bar = not app.show_gcode_ctl_bar


class BoxStencil(BoxLayout, StencilView):
    pass


class ConfirmPopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super(ConfirmPopup, self).__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False


class MessagePopup(ModalView):
    def __init__(self, **kwargs):
        super(MessagePopup, self).__init__(**kwargs)


class InputPopup(ModalView):
    cache_var1 = StringProperty('')
    cache_var2 = StringProperty('')
    cache_var3 = StringProperty('')

    def __init__(self, **kwargs):
        super(InputPopup, self).__init__(**kwargs)


class ProgressPopup(ModalView):
    progress_text = StringProperty('')
    progress_value = NumericProperty('0')

    def __init__(self, **kwargs):
        super(ProgressPopup, self).__init__(**kwargs)


class OriginPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(OriginPopup, self).__init__(**kwargs)

    def selected_anchor(self):
        if self.cbx_anchor2.active:
            return 2
        elif self.cbx_4axis_origin.active:
            return 3
        elif self.cbx_current_position.active:
            return 4
        return 1


class ZProbePopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(ZProbePopup, self).__init__(**kwargs)


class XYZProbePopup(ModalView):
    def __init__(self, **kwargs):
        super(XYZProbePopup, self).__init__(**kwargs)


class LanguagePopup(ModalView):
    def __init__(self, **kwargs):
        super(LanguagePopup, self).__init__(**kwargs)


class PairingPopup(ModalView):
    pairing = BooleanProperty(0)
    countdown = NumericProperty(0)
    pairing_note = StringProperty('')
    pairing_success = False

    def __init__(self, **kwargs):
        self.pairing_string = {'start': tr._('Press the Wireless Probe until the green LED blinks quickly.'),
                               'success': tr._('Pairing Success!'),
                               'timeout': tr._('Pairing Timeout!')}
        super(PairingPopup, self).__init__(**kwargs)

    def start_pairing(self):
        self.pairing = True
        self.pairing_success = False
        self.countdown = 30
        self.pairing_note = self.pairing_string['start']
        self.countdown_event = Clock.schedule_interval(self.pairing_countdown, 1)

    def pairing_countdown(self, *args):
        self.countdown = self.countdown - 1
        if self.pairing_success:
            self.pairing = False
            self.pairing_note = self.pairing_string['success']
            self.countdown_event.cancel()
        elif self.countdown < 1:
            self.pairing = False
            self.pairing_note = self.pairing_string['timeout']
            self.countdown_event.cancel()


class UpgradePopup(ModalView):
    def __init__(self, **kwargs):
        super(UpgradePopup, self).__init__(**kwargs)


class AutoLevelPopup(ModalView):
    execute = False

    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(AutoLevelPopup, self).__init__(**kwargs)

    def init(self):
        x_steps = int(self.sp_x_points.text)
        y_steps = int(self.sp_y_points.text)
        self.lb_min_x.text = "{:.2f}".format(CNC.vars['xmin'])
        self.lb_max_x.text = "{:.2f}".format(CNC.vars['xmax'])
        self.lb_step_x.text = "{:.2f}".format((CNC.vars['xmax'] - CNC.vars['xmin']) * 1.0 / x_steps)
        self.lb_min_y.text = "{:.2f}".format(CNC.vars['ymin'])
        self.lb_max_y.text = "{:.2f}".format(CNC.vars['ymax'])
        self.lb_step_y.text = "{:.2f}".format((CNC.vars['ymax'] - CNC.vars['ymin']) * 1.0 / y_steps)

    def init_and_open(self, execute=False):
        self.execute = execute
        self.init()
        self.open()


class UpgradePopup(ModalView):
    def __init__(self, **kwargs):
        super(UpgradePopup, self).__init__(**kwargs)


class FilePopup(ModalView):
    firmware_mode = BooleanProperty(False)

    def __init__(self, **kwargs):
        super(FilePopup, self).__init__(**kwargs)

    def load_remote_page(self):
        self.popup_manager.transition.direction = 'right'
        self.popup_manager.transition.duration = 0.3
        self.popup_manager.current = 'remote_page'
        app = App.get_running_app()
        if app.state == 'Idle':
            self.remote_rv.current_dir()

    # -----------------------------------------------------------------------
    def load_remote_root(self):
        self.remote_rv.child_dir('')

    # -----------------------------------------------------------------------
    def update_local_buttons(self):
        has_select = False
        app = App.get_running_app()
        for key in self.local_rv.view_adapter.views:
            if self.local_rv.view_adapter.views[key].selected and not self.local_rv.view_adapter.views[
                key].selected_dir:
                has_select = True
                break
        self.btn_view.disabled = (not self.firmware_mode and not has_select) or (
                self.firmware_mode and app.state != 'Idle')
        self.btn_upload.disabled = not has_select or app.state != 'Idle'

    # -----------------------------------------------------------------------
    def update_remote_buttons(self):
        has_select = False
        select_dir = False
        for key in self.remote_rv.view_adapter.views:
            if self.remote_rv.view_adapter.views[key].selected:
                has_select = True
                if self.remote_rv.view_adapter.views[key].selected_dir:
                    select_dir = True
                break
        self.btn_delete.disabled = not has_select
        self.btn_rename.disabled = not has_select
        self.btn_select.disabled = (not has_select) or select_dir


class CoordPopup(ModalView):
    config = {}
    mode = StringProperty()
    vacuummode = ObjectProperty()
    origin_popup = ObjectProperty()
    zprobe_popup = ObjectProperty()
    auto_level_popup = ObjectProperty()
    setx_popup = ObjectProperty()
    sety_popup = ObjectProperty()
    setz_popup = ObjectProperty()
    seta_popup = ObjectProperty()
    MoveA_popup = ObjectProperty()

    def __init__(self, config, **kwargs):
        self.config = config
        self.origin_popup = OriginPopup(self)
        self.zprobe_popup = ZProbePopup(self)
        self.auto_level_popup = AutoLevelPopup(self)
        self.setx_popup = SetXPopup(self)
        self.sety_popup = SetYPopup(self)
        self.setz_popup = SetZPopup(self)
        self.seta_popup = SetAPopup(self)
        self.MoveA_popup = MoveAPopup(self)
        self.mode = 'Run'  # 'Margin' / 'ZProbe' / 'Leveling'
        super(CoordPopup, self).__init__(**kwargs)

    def set_config(self, key1, key2, value):
        self.config[key1][key2] = value
        self.cnc_workspace.draw()

    def load_config(self):
        self.cnc_workspace.load_config(self.config)
        Clock.schedule_once(self.cnc_workspace.draw, 0)

        # init origin popup
        self.origin_popup.cbx_anchor1.active = self.config['origin']['anchor'] == 1
        self.origin_popup.cbx_anchor2.active = self.config['origin']['anchor'] == 2
        self.origin_popup.cbx_4axis_origin.active = self.config['origin']['anchor'] == 3
        self.origin_popup.cbx_current_position.active = self.config['origin']['anchor'] == 4
        self.origin_popup.txt_x_offset.text = str(self.config['origin']['x_offset'])
        self.origin_popup.txt_y_offset.text = str(self.config['origin']['y_offset'])

        self.load_origin_label()

        if CNC.vars["vacuummode"] == 1:
            self.vacuummode = True
        else:
            self.vacuummode = False

        # init margin widgets
        self.cbx_margin.active = self.config['margin']['active']

        # init zprobe widgets
        self.cbx_zprobe.active = self.config['zprobe']['active']
        # init zprobe popup
        self.zprobe_popup.cbx_origin1.active = self.config['zprobe']['origin'] == 1
        self.zprobe_popup.cbx_origin2.active = self.config['zprobe']['origin'] == 2
        self.zprobe_popup.txt_x_offset.text = str(self.config['zprobe']['x_offset'])
        self.zprobe_popup.txt_y_offset.text = str(self.config['zprobe']['y_offset'])

        self.load_zprobe_label()

        # init leveling widgets
        self.cbx_leveling.active = self.config['leveling']['active']
        self.auto_level_popup.sp_x_points.text = str(self.config['leveling']['x_points'])
        self.auto_level_popup.sp_y_points.text = str(self.config['leveling']['y_points'])
        self.auto_level_popup.sp_height.text = str(self.config['leveling']['height'])
        self.load_leveling_label()

    def load_origin_label(self):
        app = App.get_running_app()
        if app.has_4axis:
            self.lb_origin.text = '(%g, %g) ' % (
                round(CNC.vars["wcox"] - CNC.vars['anchor1_x'] - CNC.vars['rotation_offset_x'], 4), \
                round(CNC.vars['wcoy'] - CNC.vars['anchor1_y'] - CNC.vars['rotation_offset_y'], 4)) + tr._(
                'from Headstock')
        else:
            laser_x = CNC.vars['laser_module_offset_x'] if CNC.vars['lasermode'] else 0.0
            laser_y = CNC.vars['laser_module_offset_y'] if CNC.vars['lasermode'] else 0.0
            if self.config['origin']['anchor'] == 2:
                self.lb_origin.text = '(%g, %g) ' % (
                    round(CNC.vars['wcox'] + laser_x - CNC.vars["anchor1_x"] - CNC.vars["anchor2_offset_x"], 4), \
                    round(CNC.vars['wcoy'] + laser_y - CNC.vars["anchor1_y"] - CNC.vars["anchor2_offset_y"], 4)) + tr._(
                    'from Anchor2')
            else:
                self.lb_origin.text = '(%g, %g) ' % (round(CNC.vars['wcox'] + laser_x - CNC.vars["anchor1_x"], 4),
                                                     round(CNC.vars['wcoy'] + laser_y - CNC.vars["anchor1_y"],
                                                           4)) + tr._('from Anchor1')

    def load_zprobe_label(self):
        app = App.get_running_app()
        if app.has_4axis:
            self.lb_zprobe.text = '(%g, %g) ' % (round(CNC.vars["anchor1_x"] + CNC.vars['rotation_offset_x'] - 3, 4),
                                                 round(CNC.vars["anchor1_y"] + CNC.vars['rotation_offset_y'],
                                                       4)) + tr._('Fixed Pos')
        else:
            self.lb_zprobe.text = '(%g, %g) ' % (
                round(self.config['zprobe']['x_offset'], 4), round(self.config['zprobe']['y_offset'], 4)) + tr._('from') \
                                  + ' %s' % (tr._('Work Origin') if self.config['zprobe']['origin'] == 1 else tr._(
                'Path Origin'))

    def load_leveling_label(self):
        self.lb_leveling.text = tr._('X Points: ') + '%d ' % (self.config['leveling']['x_points']) \
                                + tr._('Y Points: ') + '%d ' % (self.config['leveling']['y_points']) \
                                + tr._('Height: ') + '%d' % (self.config['leveling']['height'])

    def toggle_config(self):
        # upldate main status
        app = App.get_running_app()
        app.root.update_coord_config()


class DiagnosePopup(ModalView):
    showing = False

    def __init__(self, **kwargs):
        super(DiagnosePopup, self).__init__(**kwargs)

    def on_open(self):
        self.showing = True

    def on_dismiss(self):
        self.showing = False


class ConfigPopup(ModalView):
    def __init__(self, **kwargs):
        super(ConfigPopup, self).__init__(**kwargs)

    def on_open(self):
        pass

    def on_dismiss(self):
        pass


class SetXPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(SetXPopup, self).__init__(**kwargs)


class SetYPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(SetYPopup, self).__init__(**kwargs)


class SetZPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(SetZPopup, self).__init__(**kwargs)


class SetAPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(SetAPopup, self).__init__(**kwargs)


class MoveAPopup(ModalView):
    def __init__(self, coord_popup, **kwargs):
        self.coord_popup = coord_popup
        super(MoveAPopup, self).__init__(**kwargs)


class MakeraConfigPanel(SettingsWithSidebar):
    def on_config_change(self, config, section, key, value):
        app = App.get_running_app()
        if not app.root.config_loading:
            if section in ['carvera', 'graphics']:
                app.root.controller_setting_change_list[key] = value
                app.root.config_popup.btn_apply.disabled = False
            elif section != 'Restore':
                app.root.setting_change_list[key] = Utils.to_config(app.root.setting_type_list[key], value).strip()
                app.root.config_popup.btn_apply.disabled = False
            elif key == 'restore' and value == 'RESTORE':
                app.root.open_setting_restore_confirm_popup()
            elif key == 'default' and value == 'DEFAULT':
                app.root.open_setting_default_confirm_popup()


class JogSpeedDropDown(DropDown):
    pass


class XDropDown(DropDown):
    pass


class YDropDown(DropDown):
    pass


class ZDropDown(DropDown):
    pass


class ADropDown(DropDown):
    pass


class FeedDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class SpindleDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class ToolDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class LaserDropDown(DropDown):
    opened = False

    def on_dismiss(self):
        self.opened = False


class FuncDropDown(DropDown):
    pass


class StatusDropDown(DropDown):
    def __init__(self, **kwargs):
        super(StatusDropDown, self).__init__(**kwargs)


class ComPortsDropDown(DropDown):
    def __init__(self, **kwargs):
        super(DropDown, self).__init__(**kwargs)


class OperationDropDown(DropDown):
    pass


class MachineButton(Button):
    ip = StringProperty("")
    port = NumericProperty(2222)
    busy = BooleanProperty(False)


class IconButton(BoxLayout, Button):
    icon = StringProperty("fresk.png")


class TransparentButton(BoxLayout, Button):
    icon = StringProperty("fresk.png")


class TransparentGrayButton(BoxLayout, Button):
    icon = StringProperty("fresk.png")


class WiFiButton(BoxLayout, Button):
    ssid = StringProperty("")
    encrypted = BooleanProperty(False)
    strength = NumericProperty(1000)
    connected = BooleanProperty(False)


class CNCWorkspace(Widget):
    config = {}

    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        self.bind(size=self.on_draw)
        super(CNCWorkspace, self).__init__(**kwargs)

    def load_config(self, config):
        self.config = config

    def draw(self, *args):
        if self.x <= 100:
            return
        self.canvas.clear()
        zoom = self.width / CNC.vars['worksize_x']
        with self.canvas:
            # background
            Color(50 / 255, 50 / 255, 50 / 255, 1)
            Rectangle(pos=self.pos, size=self.size)
            app = App.get_running_app()

            if not app.has_4axis:
                # anchor1
                if self.config['origin']['anchor'] == 1:
                    Color(75 / 255, 75 / 255, 75 / 255, 1)
                else:
                    Color(55 / 255, 55 / 255, 55 / 255, 1)
                Rectangle(pos=(self.x, self.y),
                          size=(CNC.vars['anchor_length'] * zoom, CNC.vars['anchor_width'] * zoom))
                Rectangle(pos=(self.x, self.y),
                          size=(CNC.vars['anchor_width'] * zoom, CNC.vars['anchor_length'] * zoom))

                # anchor2
                if self.config['origin']['anchor'] == 2:
                    Color(75 / 255, 75 / 255, 75 / 255, 1)
                else:
                    Color(55 / 255, 55 / 255, 55 / 255, 1)
                Rectangle(
                    pos=(self.x + CNC.vars['anchor2_offset_x'] * zoom, self.y + CNC.vars['anchor2_offset_y'] * zoom),
                    size=(CNC.vars['anchor_length'] * zoom, CNC.vars['anchor_width'] * zoom))
                Rectangle(
                    pos=(self.x + CNC.vars['anchor2_offset_x'] * zoom, self.y + CNC.vars['anchor2_offset_y'] * zoom),
                    size=(CNC.vars['anchor_width'] * zoom, CNC.vars['anchor_length'] * zoom))

            else:
                rotation_base_y_center = (CNC.vars['anchor_width'] + CNC.vars['rotation_offset_y']) * zoom
                # draw rotation base
                Color(60 / 255, 60 / 255, 60 / 255, 1)
                Rectangle(pos=(self.x, self.y + rotation_base_y_center - CNC.vars['rotation_base_height'] * zoom / 2),
                          size=(CNC.vars['rotation_base_width'] * zoom, CNC.vars['rotation_base_height'] * zoom))
                # draw rotation head
                Color(75 / 255, 75 / 255, 75 / 255, 1)
                Rectangle(pos=(self.x, self.y + rotation_base_y_center - CNC.vars['rotation_head_height'] * zoom / 2),
                          size=(CNC.vars['rotation_head_width'] * zoom, CNC.vars['rotation_head_height'] * zoom))

                # draw rotation chuck
                Color(75 / 255, 75 / 255, 75 / 255, 1)
                Rectangle(pos=(self.x + (CNC.vars['rotation_head_width'] + CNC.vars['rotation_chuck_interval']) * zoom,
                               self.y + rotation_base_y_center - CNC.vars['rotation_chuck_dia'] * zoom / 2),
                          size=(CNC.vars['rotation_chuck_width'] * zoom, CNC.vars['rotation_chuck_dia'] * zoom))

                # draw rotation tail
                Color(75 / 255, 75 / 255, 75 / 255, 1)
                Rectangle(pos=(self.x + (CNC.vars['rotation_base_width'] - CNC.vars['rotation_tail_width']) * zoom,
                               self.y + rotation_base_y_center - CNC.vars['rotation_tail_height'] * zoom / 2),
                          size=(CNC.vars['rotation_tail_width'] * zoom, CNC.vars['rotation_tail_height'] * zoom))

                # draw rotation probe position
                # Color(200 / 255, 200 / 255, 200 / 255, 1)
                # Line(points=[self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width'] - 5) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width']) * zoom,
                #              self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width'] + 5) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width']) * zoom], width=1)
                # Line(points=[self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width']) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width'] - 5) * zoom,
                #              self.x + (CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width']) * zoom, self.y + (CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width'] + 5) * zoom], width=1)

            laser_x = CNC.vars['laser_module_offset_x'] if CNC.vars['lasermode'] else 0.0
            laser_y = CNC.vars['laser_module_offset_y'] if CNC.vars['lasermode'] else 0.0

            # origin
            Color(52 / 255, 152 / 255, 219 / 255, 1)
            origin_x = CNC.vars['wcox'] - CNC.vars['anchor1_x'] + CNC.vars['anchor_width'] + laser_x
            origin_y = CNC.vars['wcoy'] - CNC.vars['anchor1_y'] + CNC.vars['anchor_width'] + laser_y
            Ellipse(pos=(self.x + origin_x * zoom - 10, self.y + origin_y * zoom - 10), size=(20, 20))

            # work area
            Color(0, 0.8, 0, 1)
            Line(width=(2 if self.config['margin']['active'] else 1), rectangle=(
                self.x + (origin_x + CNC.vars['xmin']) * zoom, self.y + (origin_y + CNC.vars['ymin']) * zoom,
                (CNC.vars['xmax'] - CNC.vars['xmin']) * zoom, (CNC.vars['ymax'] - CNC.vars['ymin']) * zoom))

            # z probe
            if self.config['zprobe']['active']:
                Color(231 / 255, 76 / 255, 60 / 255, 1)
                zprobe_x = self.config['zprobe']['x_offset'] + (
                    origin_x if self.config['zprobe']['origin'] == 1 else origin_x + CNC.vars['xmin'])
                zprobe_y = self.config['zprobe']['y_offset'] + (
                    origin_y if self.config['zprobe']['origin'] == 1 else origin_y + CNC.vars['ymin'])
                if app.has_4axis:
                    zprobe_x = CNC.vars['rotation_offset_x'] + CNC.vars['anchor_width'] - 3.0
                    zprobe_y = CNC.vars['rotation_offset_y'] + CNC.vars['anchor_width']
                Ellipse(pos=(self.x + zprobe_x * zoom - 7.5, self.y + zprobe_y * zoom - 7.5), size=(15, 15))

            # auto leveling
            if self.config['leveling']['active']:
                Color(244 / 255, 208 / 255, 63 / 255, 1)
                for x in Utils.xfrange(0.0, CNC.vars['xmax'] - CNC.vars['xmin'], self.config['leveling']['x_points']):
                    for y in Utils.xfrange(0.0, CNC.vars['ymax'] - CNC.vars['ymin'],
                                           self.config['leveling']['y_points']):
                        Ellipse(pos=(self.x + (origin_x + CNC.vars['xmin'] + x) * zoom - 5,
                                     self.y + (origin_y + CNC.vars['ymin'] + y) * zoom - 5), size=(10, 10))
                        # print('x=%f, y=%f' % (x, y))

    def on_draw(self, obj, value):
        self.draw()


class SelectableRecycleBoxLayout(FocusBehavior, LayoutSelectionBehavior,
                                 RecycleBoxLayout):
    ''' Adds selection and focus behaviour to the view. '''


class TopDataView(BoxLayout, Button):
    pass


class DirectoryView(BoxLayout, Button):
    pass


class DropDownHint(Label):
    pass


class DropDownSplitter(Label):
    pass


class SelectableLabel(RecycleDataViewBehavior, Label):
    ''' Add selection support to the Label '''
    index = None
    selected = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        ''' Catch and handle the view changes '''
        self.index = index
        return super(SelectableLabel, self).refresh_view_attrs(
            rv, index, data)

    def on_touch_down(self, touch):
        ''' Add selection on touch down '''
        if super(SelectableLabel, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            if touch.is_double_tap:
                app = App.get_running_app()
                app.root.manual_cmd.text = self.text.strip()
                Clock.schedule_once(app.root.refocus_cmd)
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        ''' Respond to the selection of items in the view. '''
        self.selected = is_selected


class SelectableBoxLayout(RecycleDataViewBehavior, BoxLayout):
    ''' Add selection support to the Label '''
    index = None
    selected = BooleanProperty(False)
    selected_dir = BooleanProperty(False)
    selectable = BooleanProperty(True)

    def refresh_view_attrs(self, rv, index, data):
        ''' Catch and handle the view changes '''
        self.index = index
        return super(SelectableBoxLayout, self).refresh_view_attrs(
            rv, index, data)

    def on_touch_down(self, touch):
        ''' Add selection on touch down '''
        if super(SelectableBoxLayout, self).on_touch_down(touch):
            return True
        if self.collide_point(*touch.pos) and self.selectable:
            if touch.is_double_tap:
                rv = self.parent.recycleview
                if rv.data[self.index]['is_dir']:
                    rv.child_dir(rv.data[self.index]['filename'])
                return True
            return self.parent.select_with_touch(self.index, touch)

    def apply_selection(self, rv, index, is_selected):
        ''' Respond to the selection of items in the view. '''
        self.selected = is_selected
        if self.selected:
            if rv.data[self.index]['is_dir']:
                self.selected_dir = True
            else:
                self.selected_dir = False
            rv.set_curr_selected_file(rv.data[self.index]['filename'], rv.data[self.index]['intsize'])
            rv.dispatch('on_select')


# -----------------------------------------------------------------------
# Data Recycle View
# -----------------------------------------------------------------------
class DataRV(RecycleView):
    curr_dir = ''
    curr_dir_name = StringProperty('')

    base_dir = ''
    base_dir_win = ''

    curr_sort_key = StringProperty('date')
    curr_sort_reverse = BooleanProperty(True)
    curr_sort_str = ListProperty(['', ' ↓', ''])

    curr_path_list = ListProperty([])
    curr_full_path_list = []
    curr_file_list_buff = []

    default_sort_reverse = {'name': False, 'date': True, 'size': False}
    search_event = None

    curr_selected_file = ''
    curr_selected_filesize = 0

    def __init__(self, **kwargs):
        super(DataRV, self).__init__(**kwargs)
        self.register_event_type('on_select')

    # -----------------------------------------------------------------------
    def on_select(self):
        pass

    # -----------------------------------------------------------------------
    def set_curr_selected_file(self, filename, filesize):
        self.curr_selected_file = os.path.join(self.curr_dir, filename)
        self.curr_selected_filesize = filesize

    # -----------------------------------------------------------------------
    def clear_selection(self):
        for key in self.view_adapter.views:
            if self.view_adapter.views[key].selected != None:
                self.view_adapter.views[key].selected = False

    # -----------------------------------------------------------------------
    def child_dir(self, child_dir):
        new_path = os.path.join(self.curr_dir, child_dir)
        self.list_dir(new_dir=new_path)

    def fill_dir(self, sort_key=None, switch_reverse=True, keyword=None):
        if sort_key == None:
            sort_key = self.curr_sort_key
        sort_reverse = self.curr_sort_reverse
        if sort_key != self.curr_sort_key:
            sort_reverse = self.default_sort_reverse[sort_key]
            self.curr_sort_reverse = sort_reverse
            self.curr_sort_key = sort_key
        else:
            if switch_reverse:
                self.curr_sort_reverse = not self.curr_sort_reverse
                sort_reverse = self.curr_sort_reverse
        if sort_key == 'name':
            self.curr_sort_str = ['↓' if sort_reverse else '↑', '', '']
        elif sort_key == 'date':
            self.curr_sort_str = ['', '↓' if sort_reverse else '↑', '']
        elif sort_key == 'size':
            self.curr_sort_str = ['', '', '↓' if sort_reverse else '↑']
        self.curr_file_list_buff = sorted(self.curr_file_list_buff, key=lambda x: x[sort_key], reverse=sort_reverse)

        filtered_list = []
        app = App.get_running_app()
        if app.root.file_popup.firmware_mode:
            filtered_list = filter(lambda x: x['is_dir'] or 'firmware' in x['name'], self.curr_file_list_buff)
        else:
            if keyword == None or keyword.strip() == '':
                filtered_list = self.curr_file_list_buff
            else:
                filtered_list = filter(lambda x: keyword.lower() in x['name'].lower(), self.curr_file_list_buff)

        # fill out the list
        self.clear_selection()
        self.data = []
        rv_key = 0
        for file in filtered_list:
            self.data.append({'rv_key': rv_key, 'filename': file['name'], 'intsize': file['size'],
                              'filesize': '--' if file['is_dir'] else Utils.humansize(file['size']),
                              'filedate': Utils.humandate(file['date']), 'is_dir': file['is_dir']})
            rv_key += 1
        # trigger
        self.dispatch('on_select')

    def goto_path(self, index):
        if index < len(self.curr_full_path_list):
            app = App.get_running_app()
            app.root.file_popup.ti_local_search.text = ''
            self.list_dir(new_dir=self.curr_full_path_list[index])

    def delay_search(self, keyword):
        # if keyword == None or keyword.strip() == '':
        #    return
        if self.search_event is not None:
            self.search_event.cancel()
        self.search_event = Clock.schedule_once(partial(self.execute_search, keyword), 1)

    def execute_search(self, keyword, *args):
        self.fill_dir(keyword=keyword, switch_reverse=False)
        self.search_event = None


# -----------------------------------------------------------------------
# Remote Recycle View
# -----------------------------------------------------------------------
class RemoteRV(DataRV):
    # -----------------------------------------------------------------------
    def __init__(self, **kwargs):
        super(RemoteRV, self).__init__(**kwargs)
        self.register_event_type('on_select')

        self.base_dir = '/sd/gcodes'
        self.base_dir_win = '\\sd\\gcodes'

        self.curr_dir = self.base_dir
        self.curr_dir_name = 'gcodes'

    # -----------------------------------------------------------------------
    def parent_dir(self):
        normpath = os.path.normpath(self.curr_dir)
        if normpath == self.base_dir or normpath == self.base_dir_win:
            self.list_dir(new_dir=normpath)
        else:
            self.list_dir(new_dir=os.path.dirname(normpath))

    # -----------------------------------------------------------------------
    def current_dir(self, *args):
        self.list_dir(new_dir=os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir=None):
        if new_dir == None:
            new_dir = self.curr_dir

        self.clear_selection()
        self.curr_file_list_buff = []

        app = App.get_running_app()
        app.root.loadRemoteDir(new_dir)
        self.curr_dir = str(new_dir)
        # self.curr_dir_name = os.path.normpath(self.curr_dir)


# -----------------------------------------------------------------------
# Local Recycle View
# -----------------------------------------------------------------------
class LocalRV(DataRV):

    def __init__(self, **kwargs):
        super(LocalRV, self).__init__(**kwargs)
        self.register_event_type('on_select')

        self.curr_dir = os.path.abspath('./gcodes')
        if not os.path.exists(self.curr_dir):
            self.curr_dir = os.path.join(os.path.dirname(__file__), 'gcodes')
        self.curr_dir_name = os.path.basename(os.path.normpath(self.curr_dir))

    # -----------------------------------------------------------------------
    def parent_dir(self):
        self.list_dir(new_dir=os.path.abspath(os.path.join(self.curr_dir, os.pardir)))

    # -----------------------------------------------------------------------
    def list_dir(self, new_dir=None):
        if new_dir == None:
            new_dir = self.curr_dir

        if not new_dir.endswith(os.path.sep):
            new_dir += os.path.sep

        self.curr_file_list_buff = []
        for (dirpath, dirnames, filenames) in os.walk(new_dir):
            for dirname in dirnames:
                if not dirname.startswith('.'):
                    file_time = 0
                    file_path = os.path.join(new_dir, dirname)
                    try:
                        file_time = os.stat(file_path).st_mtime
                    except:
                        continue
                    self.curr_file_list_buff.append({'name': dirname, 'path': file_path,
                                                     'is_dir': True, 'size': 0, 'date': file_time})
            for filename in filenames:
                if not filename.startswith('.'):
                    file_size = 0
                    file_time = 0
                    file_path = os.path.join(new_dir, filename)
                    try:
                        file_size = os.stat(file_path).st_size
                        file_time = os.stat(file_path).st_mtime
                    except:
                        continue
                    self.curr_file_list_buff.append({'name': filename, 'path': file_path,
                                                     'is_dir': False, 'size': file_size, 'date': file_time})
            break

        self.fill_dir(switch_reverse=False)

        self.curr_dir = os.path.normpath(new_dir)
        win_drivers = ['%s:' % d for d in string.ascii_uppercase]
        win_drivers_slash = ['%s:\\' % d for d in string.ascii_uppercase]
        if self.curr_dir in win_drivers or self.curr_dir in win_drivers_slash:
            self.curr_dir_name = self.curr_dir
        else:
            self.curr_dir_name = os.path.basename(self.curr_dir)

        if self.curr_dir_name == self.base_dir:
            self.curr_dir_name = 'root'

        self.curr_full_path_list = [self.curr_dir]
        self.curr_path_list = [self.curr_dir_name]
        last_parent_dir = self.curr_dir

        for loop in range(5):
            # parent_dir = os.path.abspath(os.path.join(last_parent_dir, os.pardir))
            parent_dir = os.path.dirname(last_parent_dir)
            if last_parent_dir == parent_dir:
                break
            else:
                self.curr_full_path_list.insert(0, parent_dir)
                if parent_dir in win_drivers or parent_dir in win_drivers_slash:
                    self.curr_path_list.insert(0, parent_dir)
                else:
                    self.curr_path_list.insert(0, os.path.basename(parent_dir))
                last_parent_dir = parent_dir

        if self.curr_path_list[0] == self.base_dir:
            self.curr_path_list[0] = 'root'


# -----------------------------------------------------------------------
# GCode Recycle View
# -----------------------------------------------------------------------
class GCodeRV(RecycleView):
    data_length = 0
    scroll_time = 0
    old_selected_line = 0
    new_selected_line = 0

    def __init__(self, **kwargs):
        super(GCodeRV, self).__init__(**kwargs)

    def on_scroll_stop(self, touch):
        super(GCodeRV, self).on_scroll_stop(touch)
        self.scroll_time = time.time()

    def select_line(self, *args):
        old_line = self.view_adapter.get_visible_view(self.old_selected_line)
        new_line = self.view_adapter.get_visible_view(self.new_selected_line)
        if old_line:
            old_line.selected = False
        if new_line:
            new_line.selected = True
            self.old_selected_line = self.new_selected_line

    def set_selected_line(self, line):
        app = App.get_running_app()
        aiming_page = int(line / MAX_LOAD_LINES) + (0 if line % MAX_LOAD_LINES == 0 else 1)
        if aiming_page != app.curr_page:
            app.root.load_page(aiming_page)
        line = line % MAX_LOAD_LINES
        if line != self.old_selected_line:
            if self.data_length > 0 and line < self.data_length:
                page_lines = len(self.view_adapter.views)
                self.new_selected_line = line - 1
                Clock.schedule_once(self.select_line, 0)
                if time.time() - self.scroll_time > 3:
                    scroll_value = Utils.translate(line + 1, page_lines / 2 - 1, self.data_length - page_lines / 2 + 1,
                                                   1.0, 0.0)
                    if scroll_value < 0:
                        scroll_value = 0
                    if scroll_value > 1:
                        scroll_value = 1
                    self.scroll_y = scroll_value


# -----------------------------------------------------------------------
# Manual Recycle View
# -----------------------------------------------------------------------
class ManualRV(RecycleView):

    def __init__(self, **kwargs):
        super(ManualRV, self).__init__(**kwargs)


class TopBar(BoxLayout):
    pass


class BottomBar(BoxLayout):
    pass


# -----------------------------------------------------------------------
class Content(ScreenManager):
    pass


# Declare both screens
class FilePage(Screen):
    pass


class ControlPage(Screen):
    pass


class SettingPage(Screen):
    pass


# -----------------------------------------------------------------------
class CMDManager(ScreenManager):
    pass


class GCodeCMDPage(Screen):
    pass


class ManualCMDPage(Screen):
    pass


# -----------------------------------------------------------------------
class PopupManager(ScreenManager):
    pass


class RemotePage(Screen):
    pass


class LocalPage(Screen):
    pass


class Makera(RelativeLayout):
    holding = 0
    pausing = 0
    waiting = 0
    tooling = 0
    loading_dir = ''

    stop = threading.Event()
    load_event = threading.Event()
    machine_detector = MachineDetector()
    file_popup = ObjectProperty()
    coord_popup = ObjectProperty()
    diagnose_popup = ObjectProperty()
    probing_popup = ObjectProperty()
    config_popup = ObjectProperty()
    x_drop_down = ObjectProperty()
    y_drop_down = ObjectProperty()
    z_drop_down = ObjectProperty()
    a_drop_down = ObjectProperty()

    feed_drop_down = ObjectProperty()
    spindle_drop_down = ObjectProperty()
    tool_drop_down = ObjectProperty()
    laser_drop_down = ObjectProperty()
    func_drop_down = ObjectProperty()
    status_drop_down = ObjectProperty()

    operation_drop_down = ObjectProperty()

    confirm_popup = ObjectProperty()
    message_popup = ObjectProperty()
    progress_popup = ObjectProperty()
    input_popup = ObjectProperty()
    show_advanced_jog_controls = BooleanProperty(False)
    keyboard_jog_control = BooleanProperty(False)
    jog_speed = NumericProperty(0)

    gcode_viewer = ObjectProperty()
    gcode_playing = BooleanProperty(False)

    probing_popup = ObjectProperty()

    coord_config = {}

    progress_info = StringProperty()
    selected_file_line_count = NumericProperty(0)

    test_line = NumericProperty(1)

    config_loaded = False
    config_loading = False

    uploading = False
    uploading_size = 0
    uploading_file = ''

    downloading = False
    downloading_size = 0
    downloading_file = ''
    downloading_config = False

    setting_list = {}
    setting_type_list = {}
    setting_default_list = {}
    setting_change_list = {}

    gcode_viewer_distance = 0

    alarm_triggered = False
    tool_triggered = False

    used_tools = ListProperty()
    upcoming_tool = 0

    played_lines = 0

    show_update = True
    fw_upd_text = ''
    fw_version_new = ''
    fw_version_old = ''
    fw_version_checking = False
    fw_version_checked = False

    filetype_support = 'nc'
    filetype = ''

    fileCompressionBlocks = 0  # 文件压缩后的块数
    decompercent = 0  # carvera解压压缩文件的块数
    decompercentlast = 0  # carvera解压压缩文件的块数
    decompstatus = False
    decomptime = 0

    ctl_upd_text = ''
    ctl_version_new = ''
    ctl_version_old = ''

    common_local_dir_list = []
    recent_local_dir_list = []
    recent_remote_dir_list = []

    lines = []

    load_canceled = False

    control_list = {
        # 'control_name: [update_time, value]'
        'feedrate_scale': [0.0, 100],
        'spindle_scale': [0.0, 100],
        'vacuum_mode': [0.0, 0],
        'laser_mode': [0.0, 0],
        'laser_scale': [0.0, 100],
        'laser_test': [0.0, 0],
        'spindle_switch': [0.0, 0],
        'spindle_slider': [0.0, 0],
        'spindlefan_slider': [0.0, 0],
        'vacuum_slider': [0.0, 0],
        'laser_switch': [0.0, 0],
        'laser_slider': [0.0, 0],
        'light_switch': [0.0, 0],
        'tool_sensor_switch': [0.0, 0],
        'air_switch': [0.0, 0],
        'wp_charge_switch': [0.0, 0],
    }

    status_index = 0
    past_machine_addr = None
    allow_mdi_while_machine_running = "0"

    def __init__(self, ctl_version):
        super(Makera, self).__init__()

        self.temp_dir = tempfile.mkdtemp()
        self.ctl_version_old = ctl_version
        self.file_popup = FilePopup()

        self.cnc = CNC()
        self.controller = Controller(self.cnc, self.execCallback)
        # Fill basic global variables
        CNC.vars["state"] = NOT_CONNECTED
        CNC.vars["color"] = STATECOLOR[NOT_CONNECTED]

        self.probing_config = {
            'probing': {
                'use_switch_type_nc': 0,
                'x': 0.0,
                'y': 0.0,
                'z': 0.0,
                'a': 0.0
            },
        }

        self.coord_config = {
            'origin': {
                'anchor': 1,
                'x_offset': 0.0,
                'y_offset': 0.0
            },
            'margin': {
                'active': True
            },
            'zprobe': {
                'active': True,
                'origin': 2,
                'x_offset': 5.0,
                'y_offset': 5.0
            },
            'leveling': {
                'active': False,
                'x_points': 5,
                'y_points': 5,
                'height': 5
            }
        }
        self.update_coord_config()
        self.coord_popup = CoordPopup(self.coord_config)
        self.probing_popup = ProbingPopup(self.probing_config)
        self.xyz_probe_popup = XYZProbePopup()
        self.pairing_popup = PairingPopup()
        self.upgrade_popup = UpgradePopup()
        self.language_popup = LanguagePopup()
        self.language_popup.sp_language.values = LANGS.values()
        self.language_popup.sp_language.text = 'English'
        for lang_key in LANGS.keys():
            if lang_key == default_lang:
                self.language_popup.sp_language.text = LANGS[lang_key]
                break

        self.diagnose_popup = DiagnosePopup()

        self.x_drop_down = XDropDown()
        self.y_drop_down = YDropDown()
        self.z_drop_down = ZDropDown()
        self.a_drop_down = ADropDown()
        self.feed_drop_down = FeedDropDown()
        self.spindle_drop_down = SpindleDropDown()
        self.tool_drop_down = ToolDropDown()
        self.laser_drop_down = LaserDropDown()
        self.func_drop_down = FuncDropDown()
        self.status_drop_down = StatusDropDown()
        self.operation_drop_down = OperationDropDown()
        self.jog_speed_drop_down = JogSpeedDropDown()

        self.confirm_popup = ConfirmPopup()
        self.message_popup = MessagePopup()
        self.progress_popup = ProgressPopup()
        self.input_popup = InputPopup()

        self.comports_drop_down = DropDown(auto_width=False, width='250dp')
        self.wifi_conn_drop_down = DropDown(auto_width=False, width='250dp')

        self.wifi_ap_drop_down = DropDown(auto_width=False, width='300dp')
        self.wifi_ap_drop_down.bind(on_select=lambda instance, x: self.connWIFI(x))
        self.wifi_ap_status_bar = None

        self.local_dir_drop_down = DropDown(auto_width=False, width='190dp')
        self.local_dir_drop_down.bind(on_select=lambda instance, x: self.file_popup.local_rv.list_dir(x))

        self.remote_dir_drop_down = DropDown(auto_width=False, width='190dp')
        self.remote_dir_drop_down.bind(on_select=lambda instance, x: self.file_popup.remote_rv.list_dir(x))

        # init gcode viewer
        self.gcode_viewer = GCodeViewer()
        self.gcode_viewer_container.add_widget(self.gcode_viewer)
        self.gcode_viewer.set_frame_callback(self.gcode_play_call_back)
        self.gcode_viewer.set_play_over_callback(self.gcode_play_over_call_back)

        # init settings
        self.config = ConfigParser()
        self.config_popup = ConfigPopup()
        self.config_loaded = False
        self.config_loading = False
        self.setting_list = {}
        self.setting_type_list = {}
        self.setting_default_list = {}
        self.controller_setting_change_list = {}
        self.load_controller_config()

        self.usb_event = lambda instance, x: self.openUSB(x)
        self.wifi_event = lambda instance, x: self.openWIFI(x)

        self.heartbeat_time = 0
        self.file_just_loaded = False

        self.show_update = (Config.get('carvera', 'show_update') == '1')
        self.upgrade_popup.cbx_check_at_startup.active = self.show_update
        if self.show_update:
            self.check_for_updates()

        if Config.has_option('carvera', 'address'):
            self.past_machine_addr = Config.get('carvera', 'address')

        if Config.has_option('carvera', 'allow_mdi_while_machine_running'):
            self.allow_mdi_while_machine_running = Config.get('carvera', 'allow_mdi_while_machine_running')

        # blink timer
        Clock.schedule_interval(self.blink_state, 0.5)
        # status switch timer
        Clock.schedule_interval(self.switch_status, 8)

        #
        threading.Thread(target=self.monitorSerial).start()

    def __del__(self):
        # Cleanup the temporary directory when the app is closed
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Error cleaning up temporary directory: {e}")

        # Save the last window size. 
        # Seems that kivvy uses the window size before dpi scaling in the config, 
        # but after dp scaling in Window.size
        Config.set('graphics', 'width', int(Window.size[0] / Metrics.dp))
        Config.set('graphics', 'height', int(Window.size[1] / Metrics.dp))
        Config.write()

    def load_controller_config(self):
        config_def_file = os.path.join(os.path.dirname(__file__), 'controller_config.json')
        with open(config_def_file) as file:
            controller_config_definition = json.load(file)
        controller_config = []

        # Set default controller config values
        for setting in controller_config_definition:
            if 'default' in setting:
                Config.setdefault(setting['section'], setting['key'], setting['default'])
                setting.pop('default', None)
            controller_config.append(setting)

        self.config_popup.settings_panel.add_json_panel('Controller', Config, data=json.dumps(controller_config))

    def open_download(self):
        webbrowser.open(DOWNLOAD_ADDRESS, new=2)

    def send_bug_report(self):
        webbrowser.open('https://github.com/Carvera-Community/Carvera_Controller/issues')
        webbrowser.open('https://github.com/Carvera-Community/Carvera_Community_Firmware/issues')
        log_dir = Path.home() / ".kivy" / "logs"

        # Open the log directory with whatever native file browser is availiable
        if sys.platform == "win32":
            os.startfile(log_dir)
        else:
            # Linux and MacOS
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, log_dir])

    def open_update_popup(self):
        self.upgrade_popup.check_button.disabled = False
        self.upgrade_popup.open(self)

    def close_update_popup(self):
        if self.upgrade_popup.cbx_check_at_startup.active != self.show_update:
            self.show_update = self.upgrade_popup.cbx_check_at_startup.active
            Config.set('carvera', 'show_update', '1' if self.show_update else '0')
            Config.write()
        self.upgrade_popup.dismiss(self)

    def check_for_updates(self):
        self.fw_upd_text = ''
        self.fw_version_checked = False
        self.ctl_upd_text = ''
        UrlRequest(FW_UPD_ADDRESS, on_success=self.fw_upd_loaded)
        UrlRequest(CTL_UPD_ADDRESS, on_success=self.ctl_upd_loaded)

    def fw_upd_loaded(self, req, result):
        # parse result
        self.fw_upd_text = result

    def check_fw_version(self):
        self.upgrade_popup.fw_upd_text.text = self.fw_upd_text
        self.upgrade_popup.fw_upd_text.cursor = (0, 0)  # Position the cursor at the top of the text
        versions = re.search('\[[0-9]+\.[0-9]+\.[0-9]+\]', self.fw_upd_text)
        if versions != None:
            self.fw_version_new = versions[0][1: len(versions[0]) - 1]
            if self.fw_version_old != '':
                app = App.get_running_app()
                if Utils.digitize_v(self.fw_version_new) > Utils.digitize_v(self.fw_version_old):
                    app.fw_has_update = True
                    self.upgrade_popup.fw_version_txt.text = tr._(
                        ' New version detected: v') + self.fw_version_new + tr._(' Current: v') + self.fw_version_old
                else:
                    app.fw_has_update = False
                    self.upgrade_popup.fw_version_txt.text = tr._(' Current version: v') + self.fw_version_old
        self.fw_version_checked = False

    def ctl_upd_loaded(self, req, result):
        self.ctl_upd_text = result
        Clock.schedule_once(self.check_ctl_version, 0)

    def change_language(self, lang_desc):
        for lang_key in LANGS.keys():
            if LANGS[lang_key] == lang_desc:
                if tr.lang != lang_key:
                    tr.switch_lang(lang_key)
                    Config.set('carvera', 'language', lang_key)
                    Config.write()
        self.language_popup.dismiss()
        self.config_popup.btn_apply.disabled = True
        self.message_popup.lb_content.text = tr._('Language setting applied, restart Controller app to take effect !')
        self.message_popup.open()

    def check_ctl_version(self, *args):
        self.upgrade_popup.ctl_upd_text.text = self.ctl_upd_text
        self.upgrade_popup.ctl_upd_text.cursor = (0, 0)  # Position the cursor at the top of the text
        versions = re.search('\[[0-9]+\.[0-9]+\.[0-9]+\]', self.ctl_upd_text)
        if versions != None:
            self.ctl_version_new = versions[0][1: len(versions[0]) - 1]
            app = App.get_running_app()
            if Utils.digitize_v(self.ctl_version_new) > Utils.digitize_v(self.ctl_version_old):
                app.ctl_has_update = True
                self.upgrade_popup.ctl_version_txt.text = tr._(
                    ' New version detected: v') + self.ctl_version_new + tr._(' Current: v') + self.ctl_version_old
            else:
                app.ctl_has_update = False
                self.upgrade_popup.ctl_version_txt.text = tr._(' Current version: v') + self.ctl_version_old
        self.ctl_version_checked = True

    # -----------------------------------------------------------------------
    def play(self, file_name):
        # stop review play first
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False
        # apply and play
        self.apply(True)
        # play file
        CNC.vars["playedseconds"] = 0
        self.controller.playCommand(file_name)

    # -----------------------------------------------------------------------
    def apply(self, buffer=False):
        app = App.get_running_app()

        goto_origin = False
        apply_margin = self.coord_config['margin']['active']
        apply_zprobe = self.coord_config['zprobe']['active']
        apply_leveling = self.coord_config['leveling']['active']
        # set goto path origin flag if no ATC and not in path area
        if app.has_4axis:
            goto_origin = True
        elif not apply_margin and not apply_zprobe and not apply_leveling:
            if CNC.vars['wx'] < CNC.vars['xmin'] or CNC.vars['wx'] > CNC.vars['xmax'] or CNC.vars['wy'] < CNC.vars[
                'ymin'] \
                    or CNC.vars['wy'] > CNC.vars['ymax']:
                goto_origin = True

        zprobe_abs = False
        # calculate zprobe offset
        zprobe_offset_x = self.coord_config['zprobe']['x_offset']
        zprobe_offset_y = self.coord_config['zprobe']['y_offset']
        if self.coord_config['zprobe']['origin'] == 1:
            zprobe_offset_x = zprobe_offset_x - CNC.vars['xmin']
            zprobe_offset_y = zprobe_offset_y - CNC.vars['ymin']
        if app.has_4axis:
            zprobe_abs = True

        self.controller.autoCommand(apply_margin, apply_zprobe,
                                    zprobe_abs, apply_leveling, goto_origin,
                                    zprobe_offset_x, zprobe_offset_y, self.coord_config['leveling']['x_points'],
                                    self.coord_config['leveling']['y_points'], self.coord_config['leveling']['height'],
                                    buffer)

        # change back to last tool if needed
        if buffer and self.upcoming_tool == 0 and (apply_margin or apply_zprobe or apply_leveling):
            self.controller.bufferChangeToolCommand(CNC.vars["tool"])

    # -----------------------------------------------------------------------
    def set_work_origin(self):
        origin_x = self.coord_config['origin']['x_offset']
        origin_y = self.coord_config['origin']['y_offset']
        app = App.get_running_app()
        if not app.has_4axis:
            if self.coord_config['origin']['anchor'] == 1:
                origin_x += CNC.vars['anchor1_x']
                origin_y += CNC.vars['anchor1_y']
            elif self.coord_config['origin']['anchor'] == 2:
                origin_x += CNC.vars['anchor1_x'] + CNC.vars['anchor2_offset_x']
                origin_y += CNC.vars['anchor1_y'] + CNC.vars['anchor2_offset_y']
            else:
                origin_x += CNC.vars['mx']
                origin_y += CNC.vars['my']
        else:
            origin_x += CNC.vars['anchor1_x'] + CNC.vars['rotation_offset_x']
            origin_y += CNC.vars['anchor1_y'] + CNC.vars['rotation_offset_y']

        self.controller.wcsSetM(origin_x, origin_y, None, None)

        # refresh after 1 seconds
        Clock.schedule_once(self.refresh_work_origin, 1)

    # -----------------------------------------------------------------------
    def refresh_work_origin(self, *args):
        self.coord_popup.load_config()

    # -----------------------------------------------------------------------
    def blink_state(self, *args):
        app = App.get_running_app()
        # print(app.root.size)
        # print(self.status_data_view.size)
        if self.uploading or self.downloading:
            return
        if self.holding == 1:
            self.status_data_view.color = STATECOLOR['Hold']
            self.holding = 2
        elif self.holding == 2:
            self.status_data_view.color = STATECOLOR['Disable']
            self.holding = 1

        if self.pausing == 1:
            self.status_data_view.color = STATECOLOR['Pause']
            self.pausing = 2
        elif self.pausing == 2:
            self.status_data_view.color = STATECOLOR['Disable']
            self.pausing = 1

        if self.waiting == 1:
            self.status_data_view.color = STATECOLOR['Wait']
            self.waiting = 2
        elif self.waiting == 2:
            self.status_data_view.color = STATECOLOR['Disable']
            self.waiting = 1

        if self.tooling == 1:
            self.status_data_view.color = STATECOLOR['Tool']
            self.tooling = 2
        elif self.tooling == 2:
            self.status_data_view.color = STATECOLOR['Disable']
            self.tooling = 1

        # check heartbeat
        if self.controller.sendNUM != 0 or self.controller.loadNUM != 0:
            self.heartbeat_time = time.time()

        if self.file_just_loaded:
            self.file_just_loaded = False
            return

        if time.time() - self.heartbeat_time > HEARTBEAT_TIMEOUT and self.controller.stream:
            self.controller.close()
            self.controller.log.put((Controller.MSG_ERROR, 'ALARM: ' + tr._('Timeout, Connection lost!')))
            self.updateStatus()

    # -----------------------------------------------------------------------
    def switch_status(self, *args):
        self.status_index = self.status_index + 1
        if self.status_index >= 6:
            self.status_index = 0

    # -----------------------------------------------------------------------
    def open_comports_drop_down(self, button):
        self.comports_drop_down.clear_widgets()
        devices = sorted([x[0] for x in comports()])
        for device in devices:
            btn = Button(text=device, size_hint_y=None, height='35dp')
            btn.bind(on_release=lambda btn: self.comports_drop_down.select(btn.text))
            self.comports_drop_down.add_widget(btn)
        self.comports_drop_down.unbind(on_select=self.usb_event)
        self.comports_drop_down.bind(on_select=self.usb_event)
        self.comports_drop_down.open(button)

    def fetch_common_local_dir_list(self):
        home_path = Path.home()
        if home_path.exists():
            self.common_local_dir_list.append(
                {'name': os.path.basename(home_path), 'path': str(home_path), 'icon': 'data/folder-home.png'})
        if home_path.joinpath('Documents').exists():
            self.common_local_dir_list.append({'name': tr._('Documents'), 'path': str(home_path.joinpath('Documents')),
                                               'icon': 'data/folder-documents.png'})
        if home_path.joinpath('Downloads').exists():
            self.common_local_dir_list.append({'name': tr._('Downloads'), 'path': str(home_path.joinpath('Downloads')),
                                               'icon': 'data/folder-downloads.png'})
        if home_path.joinpath('Desktop').exists():
            self.common_local_dir_list.append({'name': tr._('Desktop'), 'path': str(home_path.joinpath('Desktop')),
                                               'icon': 'data/folder-desktop.png'})

        # android storage
        if platform == 'android':
            try:
                import android
                from android.storage import primary_external_storage_path
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])
                android_storage_path = primary_external_storage_path()
                self.common_local_dir_list.append(
                    {'name': tr._('Storage'), 'path': str(android_storage_path), 'icon': 'data/folder-home.png'})
            except:
                print('Get Android Storage Error!')

        # windows disks
        available_drives = ['%s:' % d for d in string.ascii_uppercase if os.path.exists('%s:' % d)]
        for drive in available_drives:
            self.common_local_dir_list.append(
                {'name': drive, 'path': drive, 'icon': ''})

    def fetch_recent_local_dir_list(self):
        if Config.has_section('carvera'):
            for index in range(5):
                if Config.has_option('carvera', 'local_folder_' + str(index + 1)):
                    folder = Config.get('carvera', 'local_folder_' + str(index + 1))
                    if folder:
                        self.recent_local_dir_list.append(folder)
            if len(self.recent_local_dir_list) == 0:
                self.update_recent_local_dir_list(str(os.path.abspath('./gcodes')))

    def update_recent_local_dir_list(self, new_dir):
        if new_dir in self.recent_local_dir_list:
            if self.recent_local_dir_list[0] == new_dir:
                return
            self.recent_local_dir_list.remove(new_dir)
        self.recent_local_dir_list.insert(0, new_dir)
        del self.recent_local_dir_list[5:]
        # save config
        for index in range(5):
            if index < len(self.recent_local_dir_list):
                Config.set('carvera', 'local_folder_' + str(index + 1), self.recent_local_dir_list[index])
            else:
                Config.set('carvera', 'local_folder_' + str(index + 1), '')
        Config.write()

    # -----------------------------------------------------------------------
    def open_local_dir_drop_down(self, button):
        if len(self.common_local_dir_list) == 0:
            self.fetch_common_local_dir_list()

        if len(self.recent_local_dir_list) == 0:
            self.fetch_recent_local_dir_list()

        self.local_dir_drop_down.clear_widgets()

        for common_dir in self.common_local_dir_list:
            btn = DirectoryView(full_path=common_dir['path'], data_text=common_dir['name'],
                                data_icon=common_dir['icon'], size_hint_y=None, height='30dp')
            btn.bind(on_release=lambda btn: self.local_dir_drop_down.select(btn.full_path))
            self.local_dir_drop_down.add_widget(btn)

        splitter = DropDownSplitter(text='       ' + tr._('Recent Places'))
        self.local_dir_drop_down.add_widget(splitter)

        for recent_dir in self.recent_local_dir_list:
            btn = DirectoryView(full_path=recent_dir, data_text=os.path.basename(recent_dir), data_icon='',
                                size_hint_y=None, height='30dp')
            btn.bind(on_release=lambda btn: self.local_dir_drop_down.select(btn.full_path))
            self.local_dir_drop_down.add_widget(btn)

        self.local_dir_drop_down.open(button)

    # -----------------------------------------------------------------------
    def fetch_recent_remote_dir_list(self):
        if Config.has_section('carvera'):
            for index in range(5):
                if Config.has_option('carvera', 'remote_folder_' + str(index + 1)):
                    folder = Config.get('carvera', 'remote_folder_' + str(index + 1))
                    if folder:
                        self.recent_remote_dir_list.append(folder)
            if len(self.recent_remote_dir_list) == 0:
                self.update_recent_remote_dir_list('/sd/gcodes')

    # -----------------------------------------------------------------------
    def update_recent_remote_dir_list(self, new_dir):
        if new_dir in self.recent_remote_dir_list:
            if self.recent_remote_dir_list[0] == new_dir:
                return
            self.recent_remote_dir_list.remove(new_dir)
        self.recent_remote_dir_list.insert(0, new_dir)
        del self.recent_remote_dir_list[5:]
        # save config
        for index in range(5):
            if index < len(self.recent_remote_dir_list):
                Config.set('carvera', 'remote_folder_' + str(index + 1), self.recent_remote_dir_list[index])
            else:
                Config.set('carvera', 'remote_folder_' + str(index + 1), '')
        Config.write()

    # -----------------------------------------------------------------------
    def open_remote_dir_drop_down(self, button):
        if len(self.recent_remote_dir_list) == 0:
            self.fetch_recent_remote_dir_list()

        self.remote_dir_drop_down.clear_widgets()

        splitter = DropDownSplitter(text='       ' + tr._('Recent Places'))
        self.remote_dir_drop_down.add_widget(splitter)

        for recent_dir in self.recent_remote_dir_list:
            btn = DirectoryView(full_path=recent_dir, data_text=os.path.basename(recent_dir), data_icon='',
                                size_hint_y=None, height='30dp')
            btn.bind(on_release=lambda btn: self.remote_dir_drop_down.select(btn.full_path))
            self.remote_dir_drop_down.add_widget(btn)

        self.remote_dir_drop_down.open(button)

    # -----------------------------------------------------------------------
    def reconnect_wifi_conn(self, button):
        if self.past_machine_addr:
            if not self.machine_detector.is_machine_busy(self.past_machine_addr):
                self.openWIFI(self.past_machine_addr)
            else:
                Clock.schedule_once(
                    partial(self.show_message_popup, tr._("Cannot connect, machine is busy or not availiable."), False),
                    0)
        else:
            Clock.schedule_once(
                partial(self.show_message_popup, tr._("No previous machine network address stored."), False), 0)
            self.manually_input_ip()

    def open_wifi_conn_drop_down(self, button):
        self.wifi_conn_drop_down.clear_widgets()
        btn = MachineButton(text=tr._('Searching for nearby machines...'), size_hint_y=None, height='35dp',
                            color=(180 / 255, 180 / 255, 180 / 255, 1))
        self.wifi_conn_drop_down.add_widget(btn)
        self.wifi_conn_drop_down.open(button)
        self.machine_detector.query_for_machines()
        Clock.schedule_interval(self.load_machine_list, 0.1)

    def load_machine_list(self, *args):
        machines = self.machine_detector.check_for_responses()
        if machines is None:
            # the MachineDetector is still waiting for responses from machines
            return
        Clock.unschedule(self.load_machine_list)
        self.wifi_conn_drop_down.clear_widgets()
        if len(machines) == 0:
            btn = MachineButton(text=tr._('None found, enter address manually...'), size_hint_y=None, height='35dp',
                                color=(225 / 255, 225 / 255, 225 / 255, 1))
            btn.bind(on_release=lambda btn: self.manually_input_ip())
            self.wifi_conn_drop_down.add_widget(btn)
        else:
            for machine in machines:
                btn = MachineButton(text=machine['machine'] + ('(Busy)' if machine['busy'] else ''), ip=machine['ip'],
                                    port=machine['port'], size_hint_y=None, height='35dp')
                btn.bind(on_release=lambda btn: self.wifi_conn_drop_down.select(btn.ip + ':' + str(btn.port)))
                self.wifi_conn_drop_down.add_widget(btn)
                self.wifi_conn_drop_down.unbind(on_select=self.wifi_event)
                self.wifi_conn_drop_down.bind(on_select=self.wifi_event)

    # -----------------------------------------------------------------------
    def manually_input_ip(self):
        self.input_popup.lb_title.text = tr._('Input machine network address:')
        if self.past_machine_addr:
            self.input_popup.txt_content.text = self.past_machine_addr
        else:
            self.input_popup.txt_content.text = ''
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = self.manually_open_wifi
        self.input_popup.open(self)
        self.wifi_conn_drop_down.dismiss()
        self.status_drop_down.dismiss()

    def manually_open_wifi(self):
        ip = self.input_popup.txt_content.text.strip()
        self.input_popup.dismiss()
        if not ip:
            return False
        self.store_machine_address(ip)
        self.openWIFI(ip)

    def store_machine_address(self, address):
        Config.set('carvera', 'address', address)
        Config.write()
        self.past_machine_addr = address

    # -----------------------------------------------------------------------
    def update_coord_config(self):
        self.wpb_margin.width = 50 if self.coord_config['margin']['active'] else 0
        self.wpb_zprobe.width = 50 if self.coord_config['zprobe']['active'] else 0
        self.wpb_leveling.width = 50 if self.coord_config['leveling']['active'] else 0

    # -----------------------------------------------------------------------
    # Inner loop to catch any generic exception
    # -----------------------------------------------------------------------
    def monitorSerial(self):
        while not self.stop.is_set():
            t = time.time()

            while self.controller.log.qsize() > 0:
                try:
                    msg, line = self.controller.log.get_nowait()
                    line = line.rstrip("\n")
                    line = line.rstrip("\r")

                    remote_time = re.search('time = [0-9]+', line)
                    if remote_time != None:
                        if abs(int(time.time()) - time.timezone - int(remote_time[0].split('=')[1])) > 10:
                            self.controller.syncTime()

                    remote_version = re.search('version = [0-9]+\.[0-9]+\.[0-9]+', line)
                    if remote_version != None:
                        self.fw_version_old = remote_version[0].split('=')[1]
                        if self.fw_version_new != '':
                            self.check_fw_version()

                    remote_model = re.search('del = [a-zA-Z0-9]+', line)
                    if remote_model != None:
                        Clock.schedule_once(partial(self.setUIForModel, remote_model[0].split('=')[1]), 0)

                    remote_filetype = re.search('ftype = [a-zA-Z0-9]+', line)
                    if remote_filetype != None:
                        self.filetype = remote_filetype[0].split('=')[1]

                    remote_decompercent = re.search('decompart = [0-9.]+', line)
                    if remote_decompercent != None:
                        self.decompercent = int(remote_decompercent[0].split('=')[1])

                    # hanlde specific messages
                    if 'WP PAIR SUCCESS' in line:
                        self.pairing_popup.pairing_success = True

                    if msg == Controller.MSG_NORMAL:
                        self.manual_rv.data.append({'text': line, 'color': (103 / 255, 150 / 255, 186 / 255, 1)})
                    elif msg == Controller.MSG_ERROR:
                        self.manual_rv.data.append({'text': line, 'color': (250 / 255, 105 / 255, 102 / 255, 1)})
                except:
                    print(sys.exc_info()[1])
                    break
            # Update Decompress status bar
            if self.decompstatus == True:
                if self.decompercent != self.decompercentlast:
                    self.updateCompressProgress(self.decompercent)
                    self.decompercentlast = self.decompercent
                    self.decomptime = time.time()
                else:
                    t = time.time()
                    if t - self.decomptime > 8:
                        self.updateCompressProgress(self.fileCompressionBlocks)

            # Update position if needed
            if self.controller.posUpdate:
                Clock.schedule_once(self.updateStatus, 0)
                self.controller.posUpdate = False

            # change diagnose status
            self.controller.diagnosing = self.diagnose_popup.showing
            # update diagnose if needed
            if self.controller.diagnoseUpdate:
                Clock.schedule_once(self.updateDiagnose, 0)
                self.controller.diagnoseUpdate = False

            if self.controller.loadNUM == LOAD_DIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(
                            partial(self.loadError, tr._('Error loading dir') + ' \'%s\'!' % (self.loading_dir)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(
                            partial(self.loadError, tr._('Timeout loading dir') + ' \'%s\'!' % (self.loading_dir)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.fillRemoteDir, 0)
            if self.controller.loadNUM == LOAD_RM:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, tr._('Error deleting') + ' \'%s\'!' % (
                            self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, tr._('Timeout deleting') + '\'%s\'!' % (
                            self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MV:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, tr._('Error renaming') + ' \'%s\'!' % (
                            self.file_popup.remote_rv.curr_selected_file)), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, tr._('Timeout renaming') + ' \'%s\'!' % (
                            self.file_popup.remote_rv.curr_selected_file)), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_MKDIR:
                if self.controller.loadEOF or self.controller.loadERR or t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadError, tr._('Error making dir:') + ' \'%s\'!' % (
                            self.input_popup.txt_content.text.strip())), 0)
                    elif t - self.short_load_time > SHORT_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadError, tr._('Timeout making dir:') + ' \'%s\'!' % (
                            self.input_popup.txt_content.text.strip())), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.file_popup.remote_rv.current_dir, 0)
            if self.controller.loadNUM == LOAD_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadWiFiError, tr._('Error getting WiFi info!')), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadWiFiError, tr._('Timeout getting WiFi info!')), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadWiFi, 0)
            if self.controller.loadNUM == LOAD_CONN_WIFI:
                if self.controller.loadEOF or self.controller.loadERR or t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                    if self.controller.loadERR:
                        Clock.schedule_once(partial(self.loadConnWiFiError, ''), 0)
                    elif t - self.wifi_load_time > WIFI_LOAD_TIMEOUT:
                        Clock.schedule_once(partial(self.loadConnWiFiError, tr._('Timeout connecting WiFi!')), 0)
                    self.controller.loadNUM = 0
                    self.controller.loadEOF = False
                    self.controller.loadERR = False
                    Clock.schedule_once(self.finishLoadConnWiFi, 0)

            time.sleep(0.1)

    # -----------------------------------------------------------------------
    def open_del_confirm_popup(self):
        self.confirm_popup.lb_title.text = tr._('Delete File or Dir')
        self.confirm_popup.lb_content.text = tr._('Confirm to delete file or dir') + '\'%s\'?' % (
            self.file_popup.remote_rv.curr_selected_file)
        self.confirm_popup.confirm = partial(self.removeRemoteFile, self.file_popup.remote_rv.curr_selected_file)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_halt_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        app = App.get_running_app()

        if CNC.vars["halt_reason"] in HALT_REASON:
            self.confirm_popup.lb_title.text = tr._('Machine Is Halted: ') + '%s' % (
                HALT_REASON[CNC.vars["halt_reason"]])
        else:
            self.confirm_popup.lb_title.text = tr._('Machine Is Halted!')
        self.confirm_popup.cancel = None
        if CNC.vars["halt_reason"] > 40:
            self.confirm_popup.lb_content.text = tr._('Please manually switch off/on the machine!')
            self.confirm_popup.confirm = partial(self.resetMachine)
        elif CNC.vars["halt_reason"] > 20:
            self.confirm_popup.lb_content.text = tr._('Confirm to reset machine?')
            self.confirm_popup.confirm = partial(self.resetMachine)
        else:
            self.confirm_popup.lb_content.text = tr._('Confirm to unlock machine?')
            self.confirm_popup.confirm = partial(self.unlockMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_sleep_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        self.confirm_popup.lb_title.text = tr._('Machine Is Sleeping')
        self.confirm_popup.lb_content.text = tr._('Confirm to reset machine?')
        self.confirm_popup.cancel = None
        self.confirm_popup.confirm = partial(self.resetMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def open_tool_confirm_popup(self):
        if self.confirm_popup.showing:
            return
        target_tool = str(CNC.vars['target_tool'])
        if CNC.vars['target_tool'] == 0:
            target_tool = 'Probe'
        elif CNC.vars['target_tool'] == 8888:
            target_tool = 'Laser'
        self.confirm_popup.lb_title.text = tr._('Changing Tool')
        self.confirm_popup.lb_content.text = tr._('Please change to tool: ') + '%s\n' % (target_tool) + tr._(
            'Then press \' Confirm\' or main button to proceed')
        self.confirm_popup.cancel = None
        self.confirm_popup.confirm = partial(self.changeTool)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def resetMachine(self):
        self.controller.reset()

    # -----------------------------------------------------------------------
    def changeTool(self):
        self.controller.change()

    # -----------------------------------------------------------------------
    def unlockMachine(self):
        self.controller.unlock()

    # -----------------------------------------------------------------------
    def set_local_folder_to_last_opened(self):
        self.fetch_recent_local_dir_list()

        local_path = ''
        # Find more recent directory that is still present
        for dir in self.recent_local_dir_list:
            if os.path.isdir(dir):
                break
        self.file_popup.local_rv.child_dir(dir)

    def open_rename_input_popup(self):
        self.input_popup.lb_title.text = tr._('Change name') + '\'%s\' to:' % (
            self.file_popup.remote_rv.curr_selected_file)
        self.input_popup.txt_content.text = ''
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = partial(self.renameRemoteFile, self.file_popup.remote_rv.curr_selected_file)
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_newfolder_input_popup(self):
        self.input_popup.lb_title.text = tr._('Input new folder name:')
        self.input_popup.txt_content.text = ''
        self.input_popup.txt_content.password = False
        self.input_popup.confirm = self.createRemoteDir
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def open_wifi_password_input_popup(self):
        self.input_popup.lb_title.text = tr._('Input WiFi password of') + ' %s:' % self.input_popup.cache_var1
        self.input_popup.txt_content.text = ''
        self.input_popup.txt_content.password = True
        self.input_popup.confirm = self.connectToWiFi
        self.input_popup.open(self)

    # -----------------------------------------------------------------------
    def check_and_upload(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        filename = os.path.basename(os.path.normpath(filepath))
        if len(list(filter(lambda person: person['filename'] == filename, self.file_popup.remote_rv.data))) > 0:
            # show message popup
            self.confirm_popup.lb_title.text = tr._('File Already Exists')
            self.confirm_popup.lb_content.text = tr._('Confirm to overwrite file:') + ' \n \'%s\'?' % (filename)
            self.confirm_popup.cancel = None
            self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath)
            self.confirm_popup.open(self)
        else:
            if self.file_popup.firmware_mode:
                # show message popup
                self.confirm_popup.lb_title.text = tr._('Updating Firmware')
                self.confirm_popup.lb_content.text = tr._('Reset the machine when uploading is complete.')
                self.confirm_popup.cancel = None
                self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath)
                self.confirm_popup.open(self)
            else:
                self.uploadLocalFile(filepath)

    def select_file(self, remote_path, local_cached_file_path):
        """Select a file that is already present both locally and remotely"""
        app = App.get_running_app()
        app.selected_local_filename = local_cached_file_path
        app.selected_remote_filename = remote_path
        self.wpb_play.value = 0

        Clock.schedule_once(
            partial(self.progressUpdate, 0, tr._('Loading file') + ' \n%s' % app.selected_local_filename, True), 0)
        self.load_selected_gcode_file()

    def check_upload_and_select(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        filename = os.path.basename(os.path.normpath(filepath))
        if len(list(filter(lambda person: person['filename'] == filename, self.file_popup.remote_rv.data))) > 0:
            # show message popup
            self.confirm_popup.lb_title.text = tr._('File Already Exists')
            self.confirm_popup.lb_content.text = tr._('Confirm to overwrite file:') + ' \n \'%s\'?' % (filename)
            self.confirm_popup.cancel = None
            self.confirm_popup.confirm = partial(self.uploadLocalFile, filepath, self.select_file)
            self.confirm_popup.open(self)
        else:
            self.uploadLocalFile(filepath, self.select_file)

    # -----------------------------------------------------------------------
    def view_local_file(self):
        filepath = self.file_popup.local_rv.curr_selected_file
        app = App.get_running_app()
        app.selected_local_filename = filepath

        self.file_popup.dismiss()

        self.progress_popup.progress_value = 0
        self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.progress_text = tr._('Opening local file') + '\n%s' % filepath
        self.progress_popup.open()

        threading.Thread(target=self.load_selected_gcode_file).start()
        # Clock.schedule_once(self.load_selected_gcode_file, 0)

    # -----------------------------------------------------------------------
    def load_selected_gcode_file(self, *args):
        app = App.get_running_app()
        self.load(app.selected_local_filename)

    # -----------------------------------------------------------------------
    def check_and_download(self):
        remote_path = self.file_popup.remote_rv.curr_selected_file
        remote_size = self.file_popup.remote_rv.curr_selected_filesize
        remote_post_path = remote_path.replace('/sd/', '').replace('\\sd\\', '')
        local_path = os.path.join(self.temp_dir, remote_post_path)
        app = App.get_running_app()
        app.selected_local_filename = local_path
        app.selected_remote_filename = remote_path
        self.wpb_play.value = 0

        self.downloading_file = remote_path
        self.downloading_size = remote_size
        self.downloading_config = False
        threading.Thread(target=self.doDownload).start()

    # -----------------------------------------------------------------------
    def download_config_file(self):
        app = App.get_running_app()
        app.selected_local_filename = os.path.join(self.temp_dir, 'config.txt')
        self.downloading_file = '/sd/config.txt'
        self.downloading_size = 1024 * 5
        self.downloading_config = True
        threading.Thread(target=self.doDownload).start()

    # -----------------------------------------------------------------------
    def finishLoadConfig(self, success, *args):
        if success:
            self.setting_list.clear()
            # caching config file
            config_path = os.path.join(self.temp_dir, 'config.txt')
            with open(config_path, 'r') as f:
                config_string = '[dummy_section]\n' + f.read()
            # remove notes
            config_string = re.sub(r'#.*', '', config_string)
            # replace spaces to =
            config_string = re.sub(r'([a-zA-Z])( |\t)+([a-zA-Z0-9-])', r'\1=\3', config_string)

            setting_config = ConfigParser(allow_no_value=True)
            setting_config.read_string(config_string)
            for section_name in setting_config.sections():
                for (key, value) in setting_config.items(section_name):
                    try:
                        self.setting_list[key.strip()] = value.strip()
                    except AttributeError:
                        Clock.schedule_once(partial(self.load_error, tr._(
                            'Error loading machine config setting. Possibly malformed value.\nSkipping setting key: ') + str(
                            key)), 0)

            self.load_coordinates()
            self.load_laser_offsets()
            self.setting_change_list = {}

            self.config_loaded = self.load_machine_config()
            self.config_loading = False
            self.config_popup.btn_apply.disabled = True if len(self.setting_change_list) == 0 else False
        else:
            self.controller.log.put(Controller.MSG_ERROR, tr._('Download config file error'))
            # self.controller.close()

        app = App.get_running_app()
        app.selected_local_filename = ''
        self.updateStatus()

    # -----------------------------------------------------------------------
    def doDownload(self):
        app = App.get_running_app()
        if not self.downloading_config and not os.path.exists(os.path.dirname(app.selected_local_filename)):
            # os.mkdir(os.path.dirname(app.selected_local_filename))
            os.makedirs(os.path.dirname(app.selected_local_filename))
        if os.path.exists(app.selected_local_filename):
            shutil.copyfile(app.selected_local_filename, app.selected_local_filename + '.tmp')

        Clock.schedule_once(partial(self.progressStart, tr._('Load config...') if self.downloading_config else (
                tr._('Checking') + ' \n%s' % app.selected_local_filename), \
                                    None if self.downloading_config else self.cancelProcessingFile), 0)
        self.downloading = True
        download_result = False
        try:
            tmp_filename = app.selected_local_filename + '.tmp'
            md5 = ''
            if os.path.exists(tmp_filename):
                md5 = Utils.md5(tmp_filename)
            self.controller.downloadCommand(self.downloading_file)
            self.controller.pauseStream(0.2)
            download_result = self.controller.stream.download(tmp_filename, md5, self.downloadCallback)
        except:
            print(sys.exc_info()[1])
            self.controller.resumeStream()
            self.downloading = False

        self.controller.resumeStream()
        self.downloading = False

        self.heartbeat_time = time.time()

        if download_result is None:
            os.remove(app.selected_local_filename + '.tmp')
            # show message popup
            if self.downloading_config:
                Clock.schedule_once(partial(self.finishLoadConfig, False), 0.1)
                Clock.schedule_once(partial(self.show_message_popup, tr._("Download config file error!"), False), 0.2)
            else:
                Clock.schedule_once(partial(self.show_message_popup, tr._("Download file error!"), False), 0)
        elif download_result >= 0:
            if download_result > 0:
                # download success
                if os.path.exists(app.selected_local_filename):
                    os.remove(app.selected_local_filename)
                os.rename(app.selected_local_filename + '.tmp', app.selected_local_filename)
            else:
                # MD5 same
                os.remove(app.selected_local_filename + '.tmp')
            if self.downloading_config:
                Clock.schedule_once(partial(self.progressUpdate, 100, '', True), 0)
                Clock.schedule_once(partial(self.finishLoadConfig, True), 0.1)

                Clock.schedule_once(partial(self.progressUpdate, 100, tr._('Synchronize version and time...'), True), 0)
                Clock.schedule_once(self.controller.queryTime, 0.1)
                Clock.schedule_once(self.controller.queryModel, 0.2)
                Clock.schedule_once(self.controller.queryVersion, 0.3)
                self.filetype = ''
                Clock.schedule_once(self.controller.queryFtype, 0.4)
            else:
                Clock.schedule_once(
                    partial(self.progressUpdate, 0, tr._('Open cached file') + ' \n%s' % app.selected_local_filename,
                            True), 0)
                # Clock.schedule_once(self.load_selected_gcode_file, 0.1)
                self.load_selected_gcode_file()

            if not self.downloading_config:
                self.update_recent_remote_dir_list(os.path.dirname(self.downloading_file))


        elif download_result < 0:
            os.remove(app.selected_local_filename + '.tmp')
            self.controller.log.put((Controller.MSG_NORMAL, tr._('Downloading is canceled manually.')))
            if self.downloading_config:
                Clock.schedule_once(partial(self.finishLoadConfig, False), 0)

        Clock.schedule_once(self.progressFinish, 0.1)

    # -----------------------------------------------------------------------
    def setUIForModel(self, model, *args):
        app = App.get_running_app()
        if model != app.model:
            app.model = model.strip()
            if app.model == 'CA1':
                self.tool_drop_down.set_dropdown.values = ['Probe', 'Tool: 1', 'Tool: 2', 'Tool: 3', 'Tool: 4',
                                                           'Tool: 5',
                                                           'Tool: 6', 'Laser']
                self.tool_drop_down.change_dropdown.values = ['Probe', 'Tool: 1', 'Tool: 2', 'Tool: 3', 'Tool: 4',
                                                              'Tool: 5', 'Tool: 6', 'Laser']
                CNC.vars['rotation_base_width'] = 300
                CNC.vars['rotation_head_width'] = 38

    # -----------------------------------------------------------------------
    def downloadCallback(self, packet_size, success_count, error_count):
        packets = self.downloading_size / packet_size + (1 if self.downloading_size % packet_size > 0 else 0)
        Clock.schedule_once(partial(self.progressUpdate, success_count * 100.0 / packets,
                                    tr._('Downloading') + ' \n%s' % self.downloading_file, False), 0)

    # -----------------------------------------------------------------------
    def cancelSelectFile(self):
        self.progress_popup.dismiss()
        app = App.get_running_app()
        app.selected_local_filename = ''
        app.selected_remote_filename = ''

    # -----------------------------------------------------------------------
    def startLoadWiFi(self, button):
        self.wifi_ap_drop_down.open(button)
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = tr._('WiFi: Searching for network...')
        else:
            self.wifi_ap_status_bar = WiFiButton(ssid=tr._('WiFi: Searching for network...'),
                                                 color=(180 / 255, 180 / 255, 180 / 255, 1))
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

        # load wifi AP
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()
        self.controller.loadWiFiCommand()

    # -----------------------------------------------------------------------
    def finishLoadWiFi(self, *args):
        ap_list = []
        has_connected = False
        while self.controller.load_buffer.qsize() > 0:
            ap_info = self.controller.load_buffer.get_nowait().split(',')
            if len(ap_info) > 3:
                if ap_info[3] == '1':
                    has_connected = True
                ap_list.append(
                    {'ssid': ap_info[0].replace('\x01', ' '), 'connected': True if ap_info[3] == '1' else False,
                     'encrypted': True if ap_info[1] == '1' else False, 'strength': (int)(ap_info[2])})

        self.wifi_ap_drop_down.clear_widgets()
        self.wifi_ap_status_bar = None
        self.wifi_ap_status_bar = WiFiButton(
            ssid=tr._('WiFi: Connected') if has_connected else tr._('WiFi: Not Connected'),
            color=(180 / 255, 180 / 255, 180 / 255, 1))
        self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)
        if has_connected:
            btn = WiFiButton(ssid=tr._('Close Connection'))
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(''))
            self.wifi_ap_drop_down.add_widget(btn)
        # interval
        btn = WiFiButton(height='10dp')
        self.wifi_ap_drop_down.add_widget(btn)
        for ap in ap_list:
            btn = WiFiButton(connected=ap['connected'], ssid=ap['ssid'], encrypted=ap['encrypted'],
                             strength=ap['strength'])
            btn.bind(on_release=lambda btn: self.wifi_ap_drop_down.select(btn.ssid))
            self.wifi_ap_drop_down.add_widget(btn)

    # -----------------------------------------------------------------------
    def loadWiFiError(self, error_msg, *args):
        # start loading
        if self.wifi_ap_status_bar != None:
            self.wifi_ap_status_bar.ssid = 'WiFi: ' + error_msg
        else:
            self.wifi_ap_status_bar = WiFiButton(ssid='WiFi: ' + error_msg, color=(200 / 255, 200 / 255, 200 / 255, 1))
            self.wifi_ap_drop_down.add_widget(self.wifi_ap_status_bar)

    # -----------------------------------------------------------------------
    def loadConnWiFiError(self, error_msg, *args):
        # start loading
        if error_msg == '':
            while self.controller.load_buffer.qsize() > 0:
                self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        else:
            self.message_popup.lb_content.text = error_msg
        self.message_popup.btn_ok.disabled = False

    def finishLoadConnWiFi(self, *args):
        while self.controller.load_buffer.qsize() > 0:
            self.message_popup.lb_content.text = self.controller.load_buffer.get_nowait()
        self.message_popup.btn_ok.disabled = False

    def load_coordinates(self):
        for coord_name in CNC.coord_names:
            new_name = 'coordinate.' + coord_name
            if new_name in self.setting_list:
                CNC.vars[coord_name] = float(self.setting_list[new_name])
            else:
                self.controller.log.put(
                    (Controller.MSG_ERROR, tr._('Can not load coordinate value:') + ' {}'.format(new_name)))

    def load_laser_offsets(self):
        for offset_name in CNC.laser_names:
            if offset_name in self.setting_list:
                CNC.vars[offset_name] = float(self.setting_list[offset_name])
            else:
                self.controller.log.put(
                    (Controller.MSG_ERROR, tr._('Can not load laser offset value:') + ' {}'.format(offset_name)))

    # -----------------------------------------------------------------------
    def loadRemoteDir(self, ls_dir):
        self.loading_dir = ls_dir
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_DIR
        self.controller.loadEOF = False
        self.controller.loadERR = False
        self.short_load_time = time.time()
        self.controller.lsCommand(os.path.normpath(ls_dir))

    # -----------------------------------------------------------------------
    def removeRemoteFile(self, filename):
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_RM
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        self.controller.rmCommand(os.path.normpath(filename))

    # -----------------------------------------------------------------------
    def renameRemoteFile(self, filename):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MV
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        new_name = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        if filename == new_name:
            return False
        self.controller.mvCommand(os.path.normpath(filename), os.path.normpath(new_name))
        return True

    # -----------------------------------------------------------------------
    def createRemoteDir(self):
        if not self.input_popup.txt_content.text.strip():
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_MKDIR
        self.controller.readEOF = False
        self.controller.readERR = False
        self.short_load_time = time.time()
        dirname = os.path.join(self.file_popup.remote_rv.curr_dir, self.input_popup.txt_content.text)
        self.controller.mkdirCommand(os.path.normpath(dirname))
        return True

    # -----------------------------------------------------------------------
    def connectToWiFi(self):
        password = self.input_popup.txt_content.text.strip()
        if not password:
            return False
        self.controller.sendNUM = 0
        self.controller.loadNUM = LOAD_CONN_WIFI
        self.controller.readEOF = False
        self.controller.readERR = False
        self.wifi_load_time = time.time()

        Clock.schedule_once(
            partial(self.show_message_popup, tr._('Connecting to') + ' %s...\n' % self.input_popup.cache_var1, True), 0)

        self.controller.connectWiFiCommand(self.input_popup.cache_var1, password)
        return True

    # -----------------------------------------------------------------------
    def show_message_popup(self, message, btn_disabled, *args):
        self.message_popup.lb_content.text = message
        self.message_popup.btn_ok.disabled = btn_disabled
        self.message_popup.open()

    # -----------------------------------------------------------------------
    def compress_file(self, input_filename):
        try:
            # 如果上传的文件为固件，则直接返回原文件名不进行压缩
            if input_filename.find('.bin') != -1:
                return input_filename
            # 打开输入文件和输出文件
            output_filename = input_filename + '.lz'
            sum = 0
            self.fileCompressionBlocks = 0
            self.decompercent = 0
            self.decompercentlast = 0
            with open(input_filename, 'rb') as f_in, open(output_filename, 'wb') as f_out:
                while True:
                    # 读取块数据
                    block = f_in.read(BLOCK_SIZE)
                    if not block:
                        break
                    # 计算sum和
                    for byte in block:
                        sum += byte
                    # 压缩块数据
                    compressed_block = quicklz.compress(block)

                    # 计算压缩后数据库的大小
                    cmprs_size = len(compressed_block)
                    buffer_hdr = struct.pack('>I', cmprs_size)
                    # 写入压缩后的块数据的长度到输出文件
                    f_out.write(buffer_hdr)
                    # 写入压缩后的块数据到输出文件
                    f_out.write(compressed_block)
                    self.fileCompressionBlocks += 1
                # 写入校验和
                sumdata = struct.pack('>H', sum & 0xffff)
                f_out.write(sumdata)

            print(f"Compression completed. Compressed file saved as '{output_filename}'.")
            return output_filename

        except Exception as e:
            print(f"Compression failed: {e}")
            if os.path.exists(output_filename):
                os.remove(output_filename)
            return None

    # -----------------------------------------------------------------------
    def decompress_file(self, input_filename, output_filename):
        try:
            # 打开输入文件和输出文件
            sum = 0
            read_size = 0
            with open(input_filename, 'rb') as f_in, open(output_filename, 'wb') as f_out:
                # 获取文件大小（以字节为单位）
                file_size = os.path.getsize(input_filename)
                while True:
                    if read_size == (file_size - 2):
                        break
                    # 读取块数据长度
                    block = f_in.read(BLOCK_HEADER_SIZE)
                    if not block:
                        break
                    blocksize = struct.unpack('>I', block)[0]
                    read_size += BLOCK_HEADER_SIZE + blocksize
                    # 读取块数据
                    block = f_in.read(blocksize)
                    # 解压缩数据
                    decompressed_block = quicklz.decompress(block)
                    # 计算sum和
                    for byte in decompressed_block:
                        sum += byte
                    # 写入解压缩后的块数据的长度到输出文件
                    f_out.write(decompressed_block)
            # 判断校验和
            with open(input_filename, 'rb') as f_in:
                f_in.seek(-2, 2)  # 从文件末尾向前移动2个字节
                sumfile = f_in.read(2)
            sumfile = struct.unpack('>H', sumfile)[0]
            sumdata = sum & 0xffff

            if (sumfile != sumdata):
                print(f"deCompress failed: sum checksum mismatch")
                return False

            print(f"deCompress completed. deCompressed file saved as '{output_filename}'.")
            return True

        except Exception as e:
            print(f"deCompress failed: {e}")
            if os.path.exists(output_filename):
                os.remove(output_filename)
            return False

    # -----------------------------------------------------------------------
    def uploadLocalFile(self, filepath, callback=None):
        self.controller.sendNUM = SEND_FILE
        self.uploading_file = filepath
        if 'lz' in self.filetype:  # 如果固件支持的上传文件类型为.lz，则进行压缩
            qlzfilename = self.compress_file(filepath)
            if qlzfilename:
                self.uploading_file = qlzfilename
        threading.Thread(target=self.doUpload, args=(callback,)).start()

    # -----------------------------------------------------------------------
    def doUpload(self, callback):
        self.uploading_size = os.path.getsize(self.uploading_file)
        remotename = os.path.join(self.file_popup.remote_rv.curr_dir,
                                  os.path.basename(os.path.normpath(self.uploading_file)))
        if self.file_popup.firmware_mode:
            remotename = '/sd/firmware.bin'
        displayname = self.uploading_file
        if displayname.endswith(".lz"):
            # 删除 ".lz" 后缀
            displayname = displayname[:-3]
        Clock.schedule_once(
            partial(self.progressStart, tr._('Uploading') + '\n%s' % displayname, self.cancelProcessingFile), 0)
        self.uploading = True
        self.controller.pauseStream(1)
        upload_result = None
        try:
            # md5 = Utils.md5(self.uploading_file)
            md5 = Utils.md5(displayname)
            self.controller.uploadCommand(os.path.normpath(remotename))
            upload_result = self.controller.stream.upload(self.uploading_file, md5, self.uploadCallback)
        except:
            self.controller.log.put((Controller.MSG_ERROR, str(sys.exc_info()[1])))
            self.controller.resumeStream()
            self.uploading = False

        self.controller.resumeStream()
        self.uploading = False

        Clock.schedule_once(self.progressFinish, 0)

        self.heartbeat_time = time.time()

        if upload_result is None:
            self.controller.log.put((Controller.MSG_NORMAL, tr._('Uploading is canceled manually.')))
            # 如果为压缩后的'.lz'文件则删除该文件
            if self.uploading_file.endswith('.lz'):
                os.remove(self.uploading_file)
        elif not upload_result:
            # 如果为压缩后的'.lz'文件则删除该文件
            if self.uploading_file.endswith('.lz'):
                os.remove(self.uploading_file)
            # show message popup
            Clock.schedule_once(partial(self.show_message_popup, tr._("Upload file error!"), False), 0)
        else:
            # copy file to application directory if needed
            remote_path = os.path.join(self.file_popup.remote_rv.curr_dir,
                                       os.path.basename(os.path.normpath(self.uploading_file)))
            remote_post_path = remote_path.replace('/sd/', '').replace('\\sd\\', '')
            local_path = os.path.join(self.temp_dir, remote_post_path)
            if self.uploading_file != local_path and not self.file_popup.firmware_mode:
                if self.uploading_file.endswith('.lz'):
                    # copy lz file to .lz dir
                    lzpath, filename = os.path.split(local_path)
                    lzpath = os.path.join(lzpath, ".lz")
                    lzpath = os.path.join(lzpath, filename)
                    if not os.path.exists(os.path.dirname(lzpath)):
                        # os.mkdir(os.path.dirname(lzpath))
                        os.makedirs(os.path.dirname(lzpath))
                    shutil.copyfile(self.uploading_file, lzpath)

                    # copy the origin file
                    origin_file = self.uploading_file[0:-3]
                    origin_path = local_path[0:-3]
                    if not os.path.exists(os.path.dirname(origin_path)):
                        # os.mkdir(os.path.dirname(origin_path))
                        os.makedirs(os.path.dirname(origin_path))
                    shutil.copyfile(origin_file, origin_path)
                else:
                    if not os.path.exists(os.path.dirname(local_path)):
                        # os.mkdir(os.path.dirname(local_path))
                        os.makedirs(os.path.dirname(local_path))
                    shutil.copyfile(self.uploading_file, local_path)
            if self.file_popup.firmware_mode:
                Clock.schedule_once(self.confirm_reset, 0)
            # update recent folder
            if not self.file_popup.firmware_mode:
                self.update_recent_local_dir_list(os.path.dirname(self.uploading_file))

            # 如果为压缩后的'.lz'文件则等待解压缩完成
            if self.uploading_file.endswith('.lz'):
                self.log = logging.getLogger('File.Decompress')
                self.decompstatus = True
                os.remove(self.uploading_file)
                self.decomptime = time.time()
                Clock.schedule_once(partial(self.progressStart, tr._('Decompressing') + '\n%s' % displayname, False),
                                    0.2)

        self.controller.sendNUM = 0
        if upload_result and callback:  # Only run callback if upload succeeded
            if self.uploading_file.endswith('.lz'):
                callback(remotename[:-3], origin_path)
            else:
                callback(remotename, local_path)

    # -----------------------------------------------------------------------
    def confirm_reset(self, *args):
        self.confirm_popup.lb_title.text = tr._('Update Finished')
        self.confirm_popup.lb_content.text = tr._('Confirm to reset the machine?')
        self.confirm_popup.confirm = partial(self.resetMachine)
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def uploadCallback(self, packet_size, total_packets, success_count, error_count):
        packets = self.uploading_size / packet_size + (1 if self.uploading_size % packet_size > 0 else 0)
        Clock.schedule_once(partial(self.progressUpdate, total_packets * 100.0 / packets, '', False), 0)

    # -----------------------------------------------------------------------
    def cancelProcessingFile(self):
        self.controller.stream.cancel_process()

    # -----------------------------------------------------------------------
    def fillRemoteDir(self, *args):
        is_dir = False
        self.file_popup.remote_rv.curr_file_list_buff = []
        while self.controller.load_buffer.qsize() > 0:
            line = self.controller.load_buffer.get_nowait().strip('\r').strip('\n')
            if len(line) > 0 and line[0] != "<":
                file_infos = line.split()
                if len(file_infos) == 3 and not file_infos[0].startswith('.') and file_infos[1].isdigit() and \
                        file_infos[2].isdigit():
                    is_dir = False
                    file_infos[0] = file_infos[0].replace('\x01', ' ')
                    if file_infos[0].endswith('/'):
                        is_dir = True
                        file_infos[0] = file_infos[0][:-1]
                    timestamp = 0
                    try:
                        timestamp = time.mktime(datetime.datetime.strptime(file_infos[2], "%Y%m%d%H%M%S").timetuple())
                    except:
                        pass
                    self.file_popup.remote_rv.curr_file_list_buff.append({'name': file_infos[0],
                                                                          'path': os.path.join(
                                                                              self.file_popup.remote_rv.curr_dir,
                                                                              file_infos[0]),
                                                                          'is_dir': is_dir, 'size': int(file_infos[1]),
                                                                          'date': timestamp})

        self.file_popup.remote_rv.fill_dir(switch_reverse=False)

        self.file_popup.remote_rv.curr_dir = os.path.normpath(self.file_popup.remote_rv.curr_dir)
        self.file_popup.remote_rv.curr_dir_name = os.path.basename(os.path.normpath(self.file_popup.remote_rv.curr_dir))

        self.file_popup.remote_rv.curr_full_path_list = [self.file_popup.remote_rv.curr_dir]
        if self.file_popup.remote_rv.curr_dir == self.file_popup.remote_rv.base_dir \
                or self.file_popup.remote_rv.curr_dir == self.file_popup.remote_rv.base_dir_win:
            self.file_popup.remote_rv.curr_path_list = ['root']
            return
        else:
            self.file_popup.remote_rv.curr_path_list = [self.file_popup.remote_rv.curr_dir_name]
        last_parent_dir = self.file_popup.remote_rv.curr_dir

        for loop in range(5):
            parent_dir = os.path.dirname(last_parent_dir)
            if last_parent_dir == parent_dir:
                break
            else:
                self.file_popup.remote_rv.curr_full_path_list.insert(0, parent_dir)
                if parent_dir == self.file_popup.remote_rv.base_dir \
                        or parent_dir == self.file_popup.remote_rv.base_dir_win:
                    self.file_popup.remote_rv.curr_path_list.insert(0, 'root')
                    break
                else:
                    self.file_popup.remote_rv.curr_path_list.insert(0, os.path.basename(parent_dir))
                last_parent_dir = parent_dir

    # -----------------------------------------------------------------------
    def loadError(self, error_msg, *args):
        # close progress popups
        self.progress_popup.dismiss()
        # show message popup
        self.message_popup.lb_content.text = error_msg
        self.message_popup.open()

        # clear load buffer other will over load
        while self.controller.load_buffer.qsize() > 0:
            self.controller.load_buffer.get_nowait()

    # --------------------------------------------------------------`---------
    def progressStart(self, text, cancel_func, *args):
        self.progress_popup.progress_text = text
        self.progress_popup.progress_value = 0
        if cancel_func:
            self.progress_popup.cancel = cancel_func
            self.progress_popup.btn_cancel.disabled = False
        else:
            self.progress_popup.btn_cancel.disabled = True
        self.progress_popup.open()

    # --------------------------------------------------------------`---------
    def progressUpdate(self, value, progress_text, button_disabled, *args):
        if progress_text != '':
            self.progress_popup.progress_text = progress_text
        self.progress_popup.btn_cancel.disabled = button_disabled
        self.progress_popup.progress_value = value

    # --------------------------------------------------------------`---------
    def progressFinish(self, *args):
        self.progress_popup.dismiss()

    # --------------------------------------------------------------`---------
    def updateCompressProgress(self, value):
        Clock.schedule_once(partial(self.progressUpdate, value * 100.0 / self.fileCompressionBlocks, '', True), 0)
        if value == self.fileCompressionBlocks:
            Clock.schedule_once(self.progressFinish, 0)
            self.decompstatus = False

    # -----------------------------------------------------------------------
    def updateStatus(self, *args):
        try:
            now = time.time()
            self.heartbeat_time = now
            app = App.get_running_app()
            if app.state != CNC.vars["state"]:
                app.state = CNC.vars["state"]
                CNC.vars["color"] = STATECOLOR[app.state]
                self.status_data_view.color = CNC.vars["color"]
                self.holding = 1 if app.state == 'Hold' else 0
                self.pausing = 1 if app.state == 'Pause' else 0
                self.waiting = 1 if app.state == 'Wait' else 0
                self.tooling = 1 if app.state == 'Tool' else 0
                # update status
                self.status_data_view.main_text = app.state
                if app.state == NOT_CONNECTED:
                    self.status_data_view.minr_text = tr._('disconnect')
                    self.status_drop_down.btn_connect_usb.disabled = False
                    self.status_drop_down.btn_connect_wifi.disabled = False
                    self.status_drop_down.btn_disconnect.disabled = True
                    self.config_loaded = False
                    self.config_loading = False
                    self.fw_version_checked = False
                else:
                    self.status_data_view.minr_text = 'WiFi' if self.controller.connection_type == CONN_WIFI else 'USB'
                    self.status_drop_down.btn_connect_usb.disabled = True
                    self.status_drop_down.btn_connect_wifi.disabled = True
                    self.status_drop_down.btn_disconnect.disabled = False

                self.status_drop_down.btn_unlock.disabled = (app.state != "Alarm" and app.state != "Sleep")
                if (CNC.vars["halt_reason"] in HALT_REASON and CNC.vars["halt_reason"] > 20) or app.state == "Sleep":
                    self.status_drop_down.btn_unlock.text = 'Reset'
                else:
                    self.status_drop_down.btn_unlock.text = 'Unlock'

            # load config, only one time per connection
            if not app.playing and not self.config_loaded and not self.config_loading and app.state == "Idle":
                self.config_loading = True
                self.download_config_file()

            # show update
            if not app.playing and self.fw_upd_text != '' and not self.fw_version_checked and app.state == "Idle":
                self.check_fw_version()

            # check alarm and sleep status
            if app.state == 'Alarm' or app.state == 'Sleep':
                if not self.alarm_triggered:
                    self.alarm_triggered = True
                    if app.state == 'Alarm':
                        self.open_halt_confirm_popup()
                    else:
                        self.open_sleep_confirm_popup()
            elif app.state == 'Tool':
                if not self.tool_triggered:
                    self.tool_triggered = True
                    self.open_tool_confirm_popup()
            else:
                if (self.alarm_triggered or self.tool_triggered) and self.confirm_popup.showing:
                    self.confirm_popup.dismiss()
                self.tool_triggered = False
                self.alarm_triggered = False

            # update x data
            self.x_data_view.main_text = "{:.3f}".format(CNC.vars["wx"])
            self.x_data_view.minr_text = "{:.3f}".format(CNC.vars["mx"])
            self.x_data_view.scale = 80.0 if app.lasering else 100.0
            # update y data
            self.y_data_view.main_text = "{:.3f}".format(CNC.vars["wy"])
            self.y_data_view.minr_text = "{:.3f}".format(CNC.vars["my"])
            self.y_data_view.scale = 80.0 if app.lasering else 100.0
            # update z data
            self.z_data_view.main_text = "{:.3f}".format(CNC.vars["wz"])
            self.z_data_view.minr_text = "{:.3f}".format(CNC.vars["mz"])
            self.z_data_view.scale = 80.0 if app.lasering or CNC.vars["max_delta"] != 0.0 else 100.0
            self.z_drop_down.status_max.value = "{:.3f}".format(CNC.vars["max_delta"])

            # update a data
            digi_len = 7 - len(str(int(CNC.vars["ma"])))
            if digi_len < 0:
                digi_len = 0
            if digi_len > 3:
                digi_len = 3
            self.a_data_view.main_text = str("{:." + str(digi_len) + "f}").format(CNC.vars["ma"])
            self.a_data_view.minr_text = "{:.3f}".format(CNC.vars["ma"])

            # update feed data
            self.feed_data_view.main_text = "{:.0f}".format(CNC.vars["curfeed"])
            self.feed_data_view.scale = CNC.vars["OvFeed"]
            self.feed_data_view.active = CNC.vars["curfeed"] > 0.0
            if self.status_index % 2 == 0:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["OvFeed"]) + " %"
            else:
                self.feed_data_view.minr_text = "{:.0f}".format(CNC.vars["tarfeed"])

            elapsed = now - self.control_list['feedrate_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setFeedScale(self.control_list['feedrate_scale'][1])
                    self.control_list['feedrate_scale'][0] = now - 2
            elif elapsed > 3 and self.feed_drop_down.opened:
                self.feed_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvFeed"]) + "%"
                self.feed_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarfeed"])
                if self.feed_drop_down.scale_slider.value != CNC.vars["OvFeed"]:
                    self.feed_drop_down.scale_slider.set_flag = True
                    self.feed_drop_down.scale_slider.value = CNC.vars["OvFeed"]

            # update spindle data
            self.spindle_data_view.main_text = "{:.0f}".format(CNC.vars["curspindle"])
            self.spindle_data_view.scale = CNC.vars["OvSpindle"]
            self.spindle_data_view.active = CNC.vars["curspindle"] > 0.0
            if self.status_index % 4 == 0:
                self.spindle_data_view.minr_text = "{:.0f}".format(CNC.vars["tarspindle"])
            elif self.status_index % 4 == 1:
                self.spindle_data_view.minr_text = "{:.0f}".format(CNC.vars["OvSpindle"]) + " %"
            elif self.status_index % 4 == 2:
                self.spindle_data_view.minr_text = "{:.1f}".format(CNC.vars["spindletemp"]) + " °C"
            else:
                self.spindle_data_view.minr_text = "Vac: {}".format('On' if CNC.vars["vacuummode"] else 'Off')

            elapsed = now - self.control_list['vacuum_mode'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumMode(self.control_list['vacuum_mode'][1])
                    self.control_list['vacuum_mode'][0] = now - 2
            elif elapsed > 3:
                if self.spindle_drop_down.vacuum_switch.active != CNC.vars["vacuummode"]:
                    self.spindle_drop_down.vacuum_switch.set_flag = True
                    self.spindle_drop_down.vacuum_switch.active = CNC.vars["vacuummode"]

            elapsed = now - self.control_list['spindle_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleScale(self.control_list['spindle_scale'][1])
                    self.control_list['spindle_scale'][0] = now - 2
            elif elapsed > 3 and self.spindle_drop_down.opened:
                self.spindle_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["OvSpindle"]) + "%"
                self.spindle_drop_down.status_target.value = "{:.0f}".format(CNC.vars["tarspindle"])
                self.spindle_drop_down.status_temp.value = "{:.1f}".format(CNC.vars["spindletemp"]) + "°C"
                if self.spindle_drop_down.scale_slider.value != CNC.vars["OvSpindle"]:
                    self.spindle_drop_down.scale_slider.set_flag = True
                    self.spindle_drop_down.scale_slider.value = CNC.vars["OvSpindle"]

            app.tool = CNC.vars["tool"]

            # update tool data
            if CNC.vars["tool"] < 0:
                if app.lasering or CNC.vars["tool"] == 8888:
                    self.tool_data_view.main_text = tr._("Laser")
                    if self.status_index % 2 == 0:
                        self.tool_data_view.minr_text = "TLO: {:.3f}".format(CNC.vars["tlo"])
                    else:
                        self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                    self.tool_drop_down.status_tlo.value = "{:.3f}".format(CNC.vars["tlo"])
                else:
                    self.tool_data_view.main_text = tr._("None")
                    self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                    self.tool_drop_down.status_tlo.value = "N/A"
            else:
                if self.status_index % 2 == 0:
                    self.tool_data_view.minr_text = "TLO: {:.3f}".format(CNC.vars["tlo"])
                else:
                    self.tool_data_view.minr_text = "WP: {:.2f}v".format(CNC.vars["wpvoltage"])
                self.tool_drop_down.status_tlo.value = "{:.3f}".format(CNC.vars["tlo"])
                if CNC.vars["tool"] == 0:
                    self.tool_data_view.main_text = tr._("Probe")
                elif CNC.vars["tool"] == 8888:
                    self.tool_data_view.main_text = tr._("Laser")
                else:
                    self.tool_data_view.main_text = "{:.0f}".format(CNC.vars["tool"])
            self.tool_drop_down.status_wpvoltage.value = "{:.2f}v".format(CNC.vars["wpvoltage"])

            self.tool_data_view.active = CNC.vars["atc_state"] in [1, 2, 3]

            # update laser status
            if CNC.vars["lasermode"]:
                if not app.lasering:
                    self.coord_popup.set_config('margin', 'active', False)
                    self.coord_popup.set_config('zprobe', 'active', False)
                    self.coord_popup.set_config('leveling', 'active', False)
                    self.coord_popup.load_config()
                    app.lasering = True
            else:
                app.lasering = False

            # update laser data
            self.laser_data_view.active = CNC.vars["lasermode"]
            self.laser_data_view.scale = CNC.vars["laserscale"]
            self.laser_data_view.main_text = "{:.1f}".format(CNC.vars["laserpower"])
            self.laser_data_view.minr_text = "{:.0f}".format(CNC.vars["laserscale"]) + " %"
            self.laser_drop_down.status_scale.value = "{:.0f}".format(CNC.vars["laserscale"]) + "%"

            elapsed = now - self.control_list['laser_mode'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    if self.control_list['laser_mode'][1]:
                        self.enable_laser_mode_confirm_popup()
                    else:
                        self.controller.setLaserMode(False)
                    self.control_list['laser_mode'][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.switch.active != CNC.vars["lasermode"]:
                    self.laser_drop_down.switch.set_flag = True
                    self.laser_drop_down.switch.active = CNC.vars["lasermode"]

            elapsed = now - self.control_list['laser_test'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserTest(self.control_list['laser_test'][1])
                    self.control_list['laser_test'][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.test_switch.active != CNC.vars["lasertesting"]:
                    self.laser_drop_down.test_switch.set_flag = True
                    self.laser_drop_down.test_switch.active = CNC.vars["lasertesting"]

            elapsed = now - self.control_list['laser_scale'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserScale(self.control_list['laser_scale'][1])
                    self.control_list['laser_scale'][0] = now - 2
            elif elapsed > 3 and self.laser_drop_down.opened:
                if self.laser_drop_down.scale_slider.value != CNC.vars["laserscale"]:
                    self.laser_drop_down.scale_slider.set_flag = True
                    self.laser_drop_down.scale_slider.value = CNC.vars["laserscale"]

            # update progress bar and set selected
            if CNC.vars["playedlines"] <= 0:
                # not playing
                app.playing = False
                self.wpb_margin.value = 0
                self.wpb_zprobe.value = 0
                self.wpb_leveling.value = 0
                self.wpb_play.value = 0
                self.progress_info = ""

                last_job_elapsed = ""
                if CNC.vars["playedseconds"] > 0:
                    last_job_elapsed = " ( {} elapsed )".format(Utils.second2hour(CNC.vars["playedseconds"]))
                # show file name on progress bar area
                if app.selected_remote_filename != '':
                    self.progress_info = ' ' + app.selected_remote_filename + last_job_elapsed
                elif app.selected_local_filename != '':
                    self.progress_info = ' ' + app.selected_local_filename + last_job_elapsed
                else:
                    self.progress_info = tr._(' No Remote File Selected') + last_job_elapsed
            else:
                app.playing = True
                # playing file remotely
                if self.played_lines != CNC.vars["playedlines"]:
                    self.played_lines = CNC.vars["playedlines"]
                    self.wpb_play.value = CNC.vars["playedpercent"]
                    self.progress_info = ''
                    if (
                            app.selected_remote_filename != '' or app.selected_local_filename != '') and self.selected_file_line_count > 0:
                        # update gcode list
                        self.gcode_rv.set_selected_line(self.played_lines)
                        # update gcode viewer
                        self.gcode_viewer.set_distance_by_lineidx(self.played_lines, 0.5)
                        # update progress info
                        self.progress_info = os.path.basename(
                            app.selected_remote_filename if app.selected_remote_filename != '' else app.selected_local_filename) + ' ( {}/{} - {}%, {} elapsed'.format( \
                            self.played_lines, self.selected_file_line_count, int(self.wpb_play.value),
                            Utils.second2hour(CNC.vars["playedseconds"]))
                        if self.wpb_play.value > 0:
                            self.progress_info = self.progress_info + ', {} to go )'.format(Utils.second2hour(
                                (100 - self.wpb_play.value) * CNC.vars["playedseconds"] / self.wpb_play.value))
                        else:
                            self.progress_info = self.progress_info + ' )'
                # playing margin
                if CNC.vars["atc_state"] == 4:
                    self.wpb_margin.value += 14
                    if self.wpb_margin.value >= 84:
                        self.wpb_margin.value = 14
                elif self.wpb_margin.value > 0:
                    self.wpb_margin.value = 84
                # playing zprobe
                if CNC.vars["atc_state"] == 5:
                    self.wpb_zprobe.value += 14
                    if self.wpb_zprobe.value >= 84:
                        self.wpb_zprobe.value = 14
                elif self.wpb_zprobe.value > 0:
                    self.wpb_zprobe.value = 84
                # playing leveling
                if CNC.vars["atc_state"] == 6:
                    self.wpb_leveling.value += 14
                    if self.wpb_leveling.value >= 84:
                        self.wpb_leveling.value = 14
                elif self.wpb_leveling.value > 0:
                    self.wpb_leveling.value = 84

        except:
            print(sys.exc_info()[1])

    # -----------------------------------------------------------------------
    def updateDiagnose(self, *args):
        try:
            now = time.time()

            app = App.get_running_app()
            # control spindle
            self.diagnose_popup.sw_spindle.disabled = CNC.vars['lasermode']
            self.diagnose_popup.sl_spindle.disabled = CNC.vars['lasermode']
            elapsed = now - self.control_list['spindle_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(self.control_list['spindle_switch'][1],
                                                     self.diagnose_popup.sl_spindle.slider.value)
                    self.control_list['spindle_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_spindle.switch.active != CNC.vars["sw_spindle"]:
                    self.diagnose_popup.sw_spindle.set_flag = True
                    self.diagnose_popup.sw_spindle.switch.active = CNC.vars["sw_spindle"]
            elapsed = now - self.control_list['spindle_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindleSwitch(self.diagnose_popup.sw_spindle.switch.active,
                                                     self.control_list['spindle_slider'][1])
                    self.control_list['spindle_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindle.slider.value != CNC.vars["sl_spindle"]:
                    self.diagnose_popup.sl_spindle.set_flag = True
                    self.diagnose_popup.sl_spindle.slider.value = CNC.vars["sl_spindle"]

            # control spindle fan
            self.diagnose_popup.sl_spindlefan.disabled = CNC.vars['lasermode']
            elapsed = now - self.control_list['spindlefan_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setSpindlefanPower(self.control_list['spindlefan_slider'][1])
                    self.control_list['spindlefan_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_spindlefan.slider.value != CNC.vars["sl_spindlefan"]:
                    self.diagnose_popup.sl_spindlefan.set_flag = True
                    self.diagnose_popup.sl_spindlefan.slider.value = CNC.vars["sl_spindlefan"]

            # control vacuum
            elapsed = now - self.control_list['vacuum_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setVacuumPower(self.control_list['vacuum_slider'][1])
                    self.control_list['vacuum_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_vacuum.slider.value != CNC.vars["sl_vacuum"]:
                    self.diagnose_popup.sl_vacuum.set_flag = True
                    self.diagnose_popup.sl_vacuum.slider.value = CNC.vars["sl_vacuum"]

            # control laser mode
            elapsed = now - self.control_list['laser_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    if self.diagnose_popup.sw_laser.switch.active:
                        self.enable_laser_mode_confirm_popup()
                    else:
                        self.controller.setLaserMode(False)
                    self.control_list['laser_switch'][0] = now - 2
            elif elapsed > 3:
                if self.laser_drop_down.switch.active != CNC.vars["lasermode"]:
                    self.laser_drop_down.switch.set_flag = True
                    self.laser_drop_down.switch.active = CNC.vars["lasermode"]

            # control laser slider
            self.diagnose_popup.sl_laser.disabled = not CNC.vars['lasermode']
            elapsed = now - self.control_list['laser_slider'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLaserPower(self.control_list['laser_slider'][1])
                    self.control_list['laser_slider'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sl_laser.slider.value != CNC.vars["sl_laser"]:
                    self.diagnose_popup.sl_laser.set_flag = True
                    self.diagnose_popup.sl_laser.slider.value = CNC.vars["sl_laser"]

            # control light
            elapsed = now - self.control_list['light_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setLightSwitch(self.control_list['light_switch'][1])
                    self.control_list['light_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_light.switch.active != CNC.vars["sw_light"]:
                    self.diagnose_popup.sw_light.set_flag = True
                    self.diagnose_popup.sw_light.switch.active = CNC.vars["sw_light"]

            # control tool sensor power
            elapsed = now - self.control_list['tool_sensor_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setToolSensorSwitch(self.control_list['tool_sensor_switch'][1])
                    self.control_list['tool_sensor_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_tool_sensor_pwr.switch.active != CNC.vars["sw_tool_sensor_pwr"]:
                    self.diagnose_popup.sw_tool_sensor_pwr.set_flag = True
                    self.diagnose_popup.sw_tool_sensor_pwr.switch.active = CNC.vars["sw_tool_sensor_pwr"]

            # control air
            elapsed = now - self.control_list['air_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setAirSwitch(self.control_list['air_switch'][1])
                    self.control_list['air_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_air.switch.active != CNC.vars["sw_air"]:
                    self.diagnose_popup.sw_air.set_flag = True
                    self.diagnose_popup.sw_air.switch.active = CNC.vars["sw_air"]

            # control pw charge power
            elapsed = now - self.control_list['wp_charge_switch'][0]
            if elapsed < 2:
                if elapsed > 0.5:
                    self.controller.setPWChargeSwitch(self.control_list['wp_charge_switch'][1])
                    self.control_list['wp_charge_switch'][0] = now - 2
            elif elapsed > 3:
                if self.diagnose_popup.sw_wp_charge_pwr.switch.active != CNC.vars["sw_wp_charge_pwr"]:
                    self.diagnose_popup.sw_wp_charge_pwr.set_flag = True
                    self.diagnose_popup.sw_wp_charge_pwr.switch.active = CNC.vars["sw_wp_charge_pwr"]

            # update states
            self.diagnose_popup.st_x_min.state = CNC.vars["st_x_min"]
            self.diagnose_popup.st_x_max.state = CNC.vars["st_x_max"]
            self.diagnose_popup.st_y_min.state = CNC.vars["st_y_min"]
            self.diagnose_popup.st_y_max.state = CNC.vars["st_y_max"]
            self.diagnose_popup.st_z_max.state = CNC.vars["st_z_max"]
            self.diagnose_popup.st_cover.state = CNC.vars["st_cover"]
            self.diagnose_popup.st_probe.state = CNC.vars["st_probe"]
            self.diagnose_popup.st_calibrate.state = CNC.vars["st_calibrate"]
            self.diagnose_popup.st_atc_home.state = CNC.vars["st_atc_home"]
            self.diagnose_popup.st_tool_sensor.state = CNC.vars["st_tool_sensor"]
            self.diagnose_popup.st_e_stop.state = CNC.vars["st_e_stop"]
        except:
            print(sys.exc_info()[1])

    def update_control(self, name, value):
        if name in self.control_list:
            self.control_list[name][0] = time.time()
            self.control_list[name][1] = value

    def moveLineIndex(self, up=True):
        if up:
            self.test_line = self.test_line - 1
        else:
            self.test_line = self.test_line + 1
        if self.test_line == 0:
            self.test_line = 1
        self.gcode_rv.set_selected_line(self.test_line - 1)

    def execCallback(self, line):
        self.manual_rv.data.append({'text': line, 'color': (200 / 255, 200 / 255, 200 / 255, 1)})

    # -----------------------------------------------------------------------
    def openUSB(self, device):
        try:
            self.controller.open(CONN_USB, device)
            self.controller.connection_type = CONN_USB
        except:
            print(sys.exc_info()[1])
        self.updateStatus()
        self.status_drop_down.select('')

    # -----------------------------------------------------------------------
    def openWIFI(self, address):
        try:
            self.controller.open(CONN_WIFI, address)
            self.controller.connection_type = CONN_WIFI
            self.store_machine_address(address.split(':')[0])
        except:
            print(sys.exc_info()[1])
        self.updateStatus()
        self.status_drop_down.select('')

    # -----------------------------------------------------------------------
    def connWIFI(self, ssid):
        if ssid == '':
            self.controller.disconnectWiFiCommand()
        else:
            # open wifi conection popup window
            self.input_popup.cache_var1 = ssid
            self.open_wifi_password_input_popup()

    # -----------------------------------------------------------------------
    def close(self):
        try:
            self.controller.close()
        except:
            print(sys.exc_info()[1])
        self.updateStatus()

    # -----------------------------------------------------------------------
    def load_machine_config(self):
        panels = self.config_popup.settings_panel.interface.content.panels

        # Need to subtract the controller config panels from count to see if machine config panels already loaded
        controller_config_panels = 0
        for panel in panels.values():
            if panel.title == 'Controller':
                controller_config_panels = 1

        if len(panels.values()) - controller_config_panels > 0:
            # already have panels, update data
            for panel in panels.values():
                children = panel.children
                for child in children:
                    if isinstance(child, SettingItem):
                        if child.key in self.setting_list:
                            new_value = self.setting_list[child.key]
                            if child.key in self.setting_type_list:
                                if self.setting_type_list[child.key] == 'bool':
                                    new_value = '1' if new_value == 'true' else '0'
                                elif self.setting_type_list[child.key] == 'numeric':
                                    new_value = new_value + '.0' if new_value.isdigit() else new_value
                            if new_value != child.value:
                                # print(child.key, child.value, new_value)
                                child.value = new_value
                        elif child.key in self.setting_default_list:
                            new_value = self.setting_default_list[child.key]
                            self.setting_change_list[child.key] = new_value
                            if new_value != child.value:
                                # print(child.key, child.value, new_value)
                                child.value = new_value
                            self.controller.log.put(
                                (Controller.MSG_NORMAL, 'Can not load config, Key: {}'.format(child.key)))

                        # restore/default are used for default config management
                        # carvera/graphics options are managed via Controller settings (not here)
                        elif child.section.lower() not in ['restore', 'default', 'carvera', 'graphics']:
                            self.controller.log.put(
                                (Controller.MSG_ERROR, tr._('Load config error, Key:') + ' {}'.format(child.key)))
                            self.controller.close()
                            self.updateStatus()
                            return False
        else:
            # no panels, create new
            config_file = 'config.json'
            if not os.path.exists(config_file):
                config_file = os.path.join(os.path.dirname(__file__), config_file)
            if not os.path.exists(config_file):
                self.controller.log.put(
                    (Controller.MSG_ERROR, tr._('Load config error, Key:') + ' {}'.format(child.key)))
                self.controller.close()
                self.updateStatus()
                return False
            with open(config_file, 'r') as fd:
                data = json.loads(fd.read())
                basic_config = []
                advanced_config = []
                restore_config = []
                self.setting_type_list.clear()
                for setting in data:
                    if 'key' in setting and 'default' in setting:
                        self.setting_default_list[setting['key']] = setting['default']
                    if 'type' in setting:
                        has_setting = False
                        if setting['type'] != 'title':
                            if 'key' in setting and 'section' in setting and setting['key'] in self.setting_list:
                                has_setting = True
                                self.config.setdefaults(setting['section'], {
                                    setting['key']: Utils.from_config(setting['type'],
                                                                      self.setting_list[setting['key']])})
                                self.setting_type_list[setting['key']] = setting['type']
                            elif 'default' in setting:
                                has_setting = True
                                self.config.setdefaults(setting['section'], {
                                    setting['key']: Utils.from_config(setting['type'], setting['default'])})
                                self.setting_type_list[setting['key']] = setting['type']
                                self.setting_change_list[setting['key']] = setting['default']
                                self.controller.log.put(
                                    (Controller.MSG_NORMAL, 'Can not load config, Key: {}'.format(setting['key'])))
                            elif setting['key'].lower() != 'restore' and setting['key'].lower() != 'default':
                                self.controller.log.put(
                                    (Controller.MSG_ERROR, 'Load config error, Key: {}'.format(setting['key'])))
                                self.controller.close()
                                self.updateStatus()
                                return False
                        else:
                            has_setting = True
                        # construct json objects
                        if has_setting:
                            if 'section' in setting and setting['section'] == 'Basic':
                                basic_config.append(setting)
                            elif 'section' in setting and setting['section'] == 'Advanced':
                                advanced_config.append(setting)
                        elif 'section' in setting and setting['section'] == 'Restore':
                            self.config.setdefaults(setting['section'], {
                                setting['key']: Utils.from_config(setting['type'], '')})
                            restore_config.append(setting)
                # clear title section
                for basic in basic_config:
                    if basic['type'] == 'title' and 'section' in basic:
                        basic.pop('section')
                    elif 'default' in basic:
                        basic.pop('default')
                for advanced in advanced_config:
                    if advanced['type'] == 'title' and 'section' in advanced:
                        advanced.pop('section')
                    elif 'default' in advanced:
                        advanced.pop('default')
                self.config_popup.settings_panel.add_json_panel('Machine - Basic', self.config,
                                                                data=json.dumps(basic_config))
                self.config_popup.settings_panel.add_json_panel('Machine - Advanced', self.config,
                                                                data=json.dumps(advanced_config))
                self.config_popup.settings_panel.add_json_panel('Machine - Restore', self.config,
                                                                data=json.dumps(restore_config))
        return True

    # -----------------------------------------------------------------------
    def toggle_jog_control_ui(self):
        app = App.get_running_app()
        app.root.show_advanced_jog_controls = not app.root.show_advanced_jog_controls  # toggle the boolean

        # Don't let the kb jog work if the advanced jog control bar is closed
        if not app.root.show_advanced_jog_controls:
            app.root.keyboard_jog_control = False
            app.root.ids.kb_jog_btn.state = 'normal'
            Window.unbind(on_key_down=self._keyboard_jog_keydown)

    def toggle_keyboard_jog_control(self):
        app = App.get_running_app()
        app.root.keyboard_jog_control = not app.root.keyboard_jog_control  # toggle the boolean

        if app.root.keyboard_jog_control:
            Window.bind(on_key_down=self._keyboard_jog_keydown)
        else:
            Window.unbind(on_key_down=self._keyboard_jog_keydown)

    def _is_popup_open(self):
        """Checks to see if any of the popups objects are open."""
        popups_to_check = [self.file_popup._is_open, self.coord_popup._is_open, self.xyz_probe_popup._is_open,
                           self.pairing_popup._is_open,
                           self.upgrade_popup._is_open, self.language_popup._is_open, self.diagnose_popup._is_open,
                           self.confirm_popup._is_open,
                           self.message_popup._is_open, self.progress_popup._is_open, self.input_popup._is_open,
                           self.config_popup._is_open, self.probing_popup._is_open]

        return any(popups_to_check)

    def _keyboard_jog_keydown(self, *args):
        app = App.get_running_app()

        # Only allow keyboard jogging when machine in a suitable state and has no popups open
        if (app.state in ['Idle', 'Run', 'Pause'] or (
                app.playing and app.state == 'Pause')) and not self._is_popup_open():
            key = args[1]  # keycode
            if key == 274:  # down button
                app.root.controller.jog_with_speed("Y{}".format(app.root.step_xy.text), app.root.jog_speed)
            elif key == 273:  # up button
                app.root.controller.jog_with_speed("Y-{}".format(app.root.step_xy.text), app.root.jog_speed)
            elif key == 275:  # right button
                app.root.controller.jog_with_speed("X{}".format(app.root.step_xy.text), app.root.jog_speed)
            elif key == 276:  # left button
                app.root.controller.jog_with_speed("X-{}".format(app.root.step_xy.text), app.root.jog_speed)
            elif key == 280:  # page up
                app.root.controller.jog_with_speed("Z{}".format(app.root.step_z.text), app.root.jog_speed)
            elif key == 281:  # page down
                app.root.controller.jog_with_speed("Z-{}".format(app.root.step_z.text), app.root.jog_speed)

    def apply_setting_changes(self):
        if self.setting_change_list:
            self.apply_machine_setting_changes()
        if self.controller_setting_change_list:
            self.apply_controller_setting_changes()

    def apply_machine_setting_changes(self):
        for key in self.setting_change_list:
            self.controller.setConfigValue(key, self.setting_change_list[key])
            time.sleep(0.1)
        self.setting_change_list.clear()
        self.config_popup.btn_apply.disabled = True
        self.message_popup.lb_content.text = tr._('Settings applied, need machine reset to take effect !')
        self.message_popup.open()

    def apply_controller_setting_changes(self):
        if self.controller_setting_change_list.get("ui_density_override") or self.controller_setting_change_list.get(
                "ui_density"):
            self.message_popup.lb_content.text = tr._('UI Density changed, restart application to apply.')
            self.message_popup.open()

        if self.controller_setting_change_list.get(
                "allow_mdi_while_machine_running") != self.allow_mdi_while_machine_running:
            self.allow_mdi_while_machine_running = self.controller_setting_change_list.get(
                "allow_mdi_while_machine_running")

        self.config_popup.btn_apply.disabled = True

    # -----------------------------------------------------------------------
    def open_setting_restore_confirm_popup(self):
        self.confirm_popup.lb_title.text = tr._('Restore Settings')
        self.confirm_popup.lb_content.text = tr._('Confirm to restore settings from default ?')
        self.confirm_popup.confirm = partial(self.restoreSettings)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def restoreSettings(self):
        self.controller.restoreConfigCommand()

    def enter_laser_mode(self):
        self.controller.setLaserMode(True)

    # -----------------------------------------------------------------------
    def open_setting_default_confirm_popup(self):
        self.confirm_popup.lb_title.text = tr._('Save As Default')
        self.confirm_popup.lb_content.text = tr._('Confirm to save current settings as default ?')
        self.confirm_popup.confirm = partial(self.defaultSettings)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    def enable_laser_mode_confirm_popup(self):
        self.confirm_popup.size_hint = (0.6, 0.7)
        self.confirm_popup.pos_hint = {'center_x': 0.5, 'center_y': 0.5}
        self.confirm_popup.lb_title.text = tr._('Entering Laser Mode')
        self.confirm_popup.lb_title.size_hint_y = None
        self.confirm_popup.lb_content.text = tr._(
            'You are about to enable laser mode. \n\nWhen enabled the current tool will be dropped, the spindle fan locked to 90%, \nand the empty spindle nose will be set as the tool and length probed.\n\n It\'s recommended to remove the laser dust cap, and put on safety glasses now.\n\nAre you read to proceed ?')
        self.confirm_popup.confirm = partial(self.enter_laser_mode)
        self.confirm_popup.cancel = None
        self.confirm_popup.open(self)

    # -----------------------------------------------------------------------
    def defaultSettings(self):
        self.controller.defaultConfigCommand()

    # -----------------------------------------------------------------------
    def gcode_play_call_back(self, distance, line_number):
        if not self.loading_file:
            self.gcode_play_slider.value = distance * 1000.0 / self.gcode_viewer_distance

    # -----------------------------------------------------------------------
    def gcode_play_over_call_back(self):
        self.gcode_playing = False

    # -----------------------------------------------------------------------
    def gcode_play_to_start(self):
        self.gcode_viewer.set_pos_by_distance(0)
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False

    # -----------------------------------------------------------------------
    def gcode_play_to_end(self):
        self.gcode_viewer.show_all()
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False

    # -----------------------------------------------------------------------
    def gcode_play_speed_up(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 2)

    # -----------------------------------------------------------------------
    def gcode_play_speed_down(self):
        self.gcode_viewer.set_move_speed(self.gcode_viewer.move_speed * 0.5)

    # -----------------------------------------------------------------------
    def gcode_play_toggle(self):
        if self.gcode_playing:
            self.gcode_playing = False
            self.gcode_viewer.dynamic_display = False
        else:
            if self.gcode_viewer.display_count >= self.gcode_viewer.get_total_distance():
                self.gcode_play_to_start()
            self.gcode_playing = True
            self.gcode_viewer.dynamic_display = True

    # -----------------------------------------------------------------------
    def clear_selection(self):
        self.gcode_rv.data = []
        self.gcode_rv.data_length = 0
        self.gcode_viewer.clearDisplay()
        self.wpb_play.value = 0
        self.used_tools = []
        self.upcoming_tool = 0
        app = App.get_running_app()
        app.curr_page = 1
        app.total_pages = 1
        self.updateStatus()

    # ------------------------------------------------------------------------
    def load_start(self, *args):
        self.loading_file = True
        self.cmd_manager.transition.direction = 'right'
        self.cmd_manager.current = 'gcode_cmd_page'
        self.gcode_rv.data = []
        self.init_tool_filter()
        self.gcode_viewer.clearDisplay()
        self.gcode_viewer.set_display_offset(self.content.x, self.content.y)
        self.gcode_viewer.set_move_speed(GCODE_VIEW_SPEED)
        self.gcode_playing = False
        self.gcode_viewer.dynamic_display = False

    # ------------------------------------------------------------------------
    def load_page(self, page_no, *args):
        app = App.get_running_app()
        app.loading_page = True
        if page_no == -1:
            page_no = 1 if app.curr_page == 1 else app.curr_page - 1
        elif page_no == 0:
            page_no = app.curr_page + 1
        if page_no > app.total_pages:
            page_no = app.total_pages
        self.gcode_rv.data = []
        line_no = (page_no - 1) * MAX_LOAD_LINES + 1
        for line in self.lines[(page_no - 1) * MAX_LOAD_LINES: MAX_LOAD_LINES * page_no]:
            line_txt = line[:-1].replace("\x0d", "")
            self.gcode_rv.data.append(
                {'text': str(line_no).ljust(12) + line_txt.strip(), 'color': (200 / 255, 200 / 255, 200 / 255, 1)})
            line_no = line_no + 1
        self.gcode_rv.data_length = len(self.gcode_rv.data)
        app.curr_page = page_no
        app.loading_page = False

    # ------------------------------------------------------------------------
    def cancel_load_gcodes(self):
        self.load_canceled = True

    # ------------------------------------------------------------------------
    def load_gcodes(self, line_no, parsed_list, *args):
        if len(parsed_list) > 0:
            self.gcode_viewer.load_array(parsed_list, line_no == self.selected_file_line_count)

        self.progress_popup.cancel = self.cancel_load_gcodes
        self.progress_popup.btn_cancel.disabled = False

        self.progress_popup.progress_value = line_no * 100.0 / self.selected_file_line_count

        self.load_event.set()

    # ------------------------------------------------------------------------
    def load_error(self, error_msg, *args):
        self.progress_popup.dismiss()
        self.message_popup.lb_content.text = error_msg
        self.message_popup.open(self)

    # ------------------------------------------------------------------------
    def load_end(self, *args):
        if self.load_canceled:
            self.gcode_viewer.load_array([], True)
            self.clear_selection()
            self.load_canceled = False
            self.file_popup.dismiss()
            self.progress_popup.dismiss()
            self.updateStatus()
            self.loading_file = False
            return

        if len(self.gcode_viewer.lengths) > 0:
            self.gcode_viewer_distance = self.gcode_viewer.get_total_distance()
            self.gcode_viewer.show_all()

        app = App.get_running_app()
        app.has_4axis = self.cnc.has_4axis
        if app.has_4axis:
            self.coord_popup.set_config('leveling', 'active', False)
            self.coord_popup.set_config('origin', 'anchor', 3)
        else:
            if (CNC.vars['wcox'] - CNC.vars['anchor1_x'] - CNC.vars['anchor2_offset_x']) >= 0 and (
                    CNC.vars['wcoy'] - CNC.vars['anchor1_y'] - CNC.vars['anchor2_offset_y']) >= 0:
                self.coord_popup.set_config('origin', 'anchor', 2)
            else:
                self.coord_popup.set_config('origin', 'anchor', 1)
        self.coord_popup.load_config()

        self.file_popup.dismiss()
        self.progress_popup.dismiss()

        self.heartbeat_time = time.time()
        self.file_just_loaded = True

        self.updateStatus()
        self.loading_file = False

    # -----------------------------------------------------------------------
    def first_page(self):
        self.load_page(1)

    # -----------------------------------------------------------------------
    def last_page(self):
        self.load_page(9999)

    # -----------------------------------------------------------------------
    def previous_page(self):
        self.load_page(-1)

    # -----------------------------------------------------------------------
    def next_page(self):
        self.load_page(0)

    # -----------------------------------------------------------------------
    def load(self, filepath):
        self.load_event.set()
        self.upcoming_tool = 0
        self.used_tools = []
        Clock.schedule_once(self.load_start)
        f = None
        try:
            with open(filepath, "rb") as f:
                # 读取文件开头的两个字节
                first_two_bytes = f.read(2)
            if first_two_bytes == b'\x00\x00':  # we just confirm this is a file compressed by quicklz
                # copy lz file to .lz dir
                lzpath, filename = os.path.split(filepath)
                lzpath = os.path.join(lzpath, ".lz")
                lzpath = os.path.join(lzpath, filename)
                if not os.path.exists(os.path.dirname(lzpath)):
                    # os.mkdir(os.path.dirname(lzpath))
                    os.makedirs(os.path.dirname(lzpath))
                lzpath = lzpath + ".lz"
                shutil.copyfile(filepath, lzpath)
                if not self.decompress_file(lzpath, filepath):
                    return

            self.cnc.init()
            f = open(filepath, "r", encoding='utf-8')
            self.lines = f.readlines()
            self.selected_file_line_count = len(self.lines)
            f.close()
            app = App.get_running_app()
            app.total_pages = int(self.selected_file_line_count / MAX_LOAD_LINES) \
                              + (0 if self.selected_file_line_count % MAX_LOAD_LINES == 0 else 1)
            Clock.schedule_once(partial(self.load_page, 1), 0)
            f = None
            line_no = 1
            # now = time.time()
            # temp_list = []
            for line in self.lines:
                if self.load_canceled:
                    break
                self.cnc.parseLine(line, line_no)
                if self.upcoming_tool == 0:
                    self.upcoming_tool = self.cnc.tool
                if self.cnc.tool not in self.used_tools:
                    self.used_tools.append(self.cnc.tool)

                if line_no % LOAD_INTERVAL == 0 or line_no == self.selected_file_line_count:
                    parsed_list = self.cnc.coordinates
                    self.load_event.wait()
                    self.load_event.clear()
                    # temp_list.extend(self.cnc.coordinates)
                    Clock.schedule_once(partial(self.load_gcodes, line_no, parsed_list), 0)
                    self.cnc.coordinates = []
                line_no += 1
            # print('Load time: ' + str(time.time() - now))
            # with open("laser.txt", "w") as output:
            #     output.write(str(temp_list))
        except:
            print(sys.exc_info()[1])
            self.heartbeat_time = time.time()
            self.loading_file = False
            if f:
                f.close()
            Clock.schedule_once(partial(self.load_error, tr._('Opening file error:') + '\n\'%s\'\n' % (filepath) + tr._(
                'Please make sure the GCode file is valid')), 0)
            return

        Clock.schedule_once(self.load_end, 0)

    # -----------------------------------------------------------------------
    def init_tool_filter(self):
        tool_buttons = [self.float_layout.t1, self.float_layout.t2, self.float_layout.t3, \
                        self.float_layout.t4, self.float_layout.t5, self.float_layout.t6, \
                        self.float_layout.laser]
        for tool_button in tool_buttons:
            tool_button.min_active = True
        self.float_layout.hide_all.active = True

    # -----------------------------------------------------------------------
    def filter_tool(self):
        mask = 0.0
        tool_buttons = [self.float_layout.t1, self.float_layout.t2, self.float_layout.t3, \
                        self.float_layout.t4, self.float_layout.t5, self.float_layout.t6, \
                        self.float_layout.laser]
        enabled_tools = []
        visible_tools = []
        for index, tool_button in enumerate(tool_buttons, start=1):
            if not tool_button.disabled:
                enabled_tools.append(index)
                if tool_button.min_active:
                    visible_tools.append(index)
        if len(enabled_tools) > 0 and enabled_tools == visible_tools:
            self.float_layout.hide_all.active = True
        else:
            self.float_layout.hide_all.active = False

        if len(enabled_tools) > 0 and len(visible_tools) == 0:
            mask = 10000000.0
        else:
            for tool in visible_tools:
                mask = mask + 10 ** (tool - 1)
        self.gcode_viewer.set_display_mask(mask)

    # -----------------------------------------------------------------------
    def send_cmd(self):
        to_send = self.manual_cmd.text.strip()
        if to_send:
            self.manual_rv.scroll_y = 0
            if to_send.lower() == "clear":
                self.manual_rv.data = []
            else:
                self.controller.executeCommand(to_send)
        self.manual_cmd.text = ''
        Clock.schedule_once(self.refocus_cmd)

    # -----------------------------------------------------------------------
    def refocus_cmd(self, dt):
        self.manual_cmd.focus = True

    def stop_run(self):
        self.stop.set()
        self.controller.stop.set()

    def start_probing(self, x, y, z, a, switch_type):
        gcode = ProbeGcodeGenerator(x, y, z, a, switch_type)
        if len(gcode) > 0:
            self.controller.executeCommand(gcode + "\n")


class MakeraApp(App):
    state = StringProperty(NOT_CONNECTED)
    playing = BooleanProperty(False)
    has_4axis = BooleanProperty(False)
    lasering = BooleanProperty(False)
    show_gcode_ctl_bar = BooleanProperty(False)
    fw_has_update = BooleanProperty(False)
    ctl_has_update = BooleanProperty(False)
    selected_local_filename = StringProperty('')
    selected_remote_filename = StringProperty('')
    tool = NumericProperty(-1)
    curr_page = NumericProperty(1)
    total_pages = NumericProperty(1)
    loading_page = BooleanProperty(False)
    model = StringProperty('C1')

    def on_stop(self):
        self.root.stop_run()

    def build(self):
        self.settings_cls = SettingsWithSidebar
        self.use_kivy_settings = True
        self.title = tr._('Carvera Controller Community') + ' v' + __version__
        self.icon = os.path.join(os.path.dirname(__file__), 'icon.png')

        return Makera(ctl_version=__version__)


def android_tweaks():
    """Android specific app changes"""
    try:
        from jnius import autoclass

        DisplayMetrics = autoclass('android.util.DisplayMetrics')
        WindowManager = autoclass('android.view.WindowManager')
        PythonActivity = autoclass('org.kivy.android.PythonActivity')

        activity = PythonActivity.mActivity
        metrics = DisplayMetrics()
        activity.getWindowManager().getDefaultDisplay().getMetrics(metrics)

        screen_width_density = int(metrics.widthPixels * 10 / 960) / 10
        screen_height_density = int(metrics.heightPixels * 10 / 550) / 10

        os.environ["KIVY_METRICS_DENSITY"] = str(min(screen_width_density, screen_height_density))

    except ImportError:
        print("Pyjnius Import Fail.")


def load_app_configs():
    if Config.has_option('carvera', 'ui_density_override') and Config.get('carvera', 'ui_density_override') == "1":
        Metrics.set_density(float(Config.get('carvera', 'ui_density')))


def set_config_defaults(default_lang):
    if not Config.has_section('carvera'):
        Config.add_section('carvera')

    # Only update config if running new version
    if not Config.has_option('carvera', 'version') or Config.get('carvera', 'version') != __version__:
        Config.set('carvera', 'version', __version__)
        # Default params that are not configurable, set only once
        Config.set('kivy', 'window_icon', 'data/icon.png')
        Config.set('kivy', 'exit_on_escape', '0')
        Config.set('kivy', 'pause_on_minimize', '0')

    # Configurable config options. Don't change if they are already set
    if not Config.has_option('carvera', 'show_update'): Config.set('carvera', 'show_update', '1')
    if not Config.has_option('carvera', 'language'): Config.set('carvera', 'language', default_lang)
    if not Config.has_option('carvera', 'local_folder_1'): Config.set('carvera', 'local_folder_1', '')
    if not Config.has_option('carvera', 'local_folder_2'): Config.set('carvera', 'local_folder_2', '')
    if not Config.has_option('carvera', 'local_folder_3'): Config.set('carvera', 'local_folder_3', '')
    if not Config.has_option('carvera', 'local_folder_4'): Config.set('carvera', 'local_folder_4', '')
    if not Config.has_option('carvera', 'local_folder_5'): Config.set('carvera', 'local_folder_5', '')
    if not Config.has_option('carvera', 'remote_folder_1'): Config.set('carvera', 'remote_folder_1', '')
    if not Config.has_option('carvera', 'remote_folder_2'): Config.set('carvera', 'remote_folder_2', '')
    if not Config.has_option('carvera', 'remote_folder_3'): Config.set('carvera', 'remote_folder_3', '')
    if not Config.has_option('carvera', 'remote_folder_4'): Config.set('carvera', 'remote_folder_4', '')
    if not Config.has_option('carvera', 'remote_folder_5'): Config.set('carvera', 'remote_folder_5', '')
    if not Config.has_option('graphics', 'allow_screensaver'): Config.set('graphics', 'allow_screensaver', '0')
    if not Config.has_option('graphics', 'width'): Config.set('graphics', 'width', '1440')
    if not Config.has_option('graphics', 'height'): Config.set('graphics', 'height', '900')
    Config.write()


def load_constants():
    Window.softinput_mode = "below_target"

    _device = None
    _baud = None

    global SHORT_LOAD_TIMEOUT
    global WIFI_LOAD_TIMEOUT
    global HEARTBEAT_TIMEOUT
    global MAX_TOUCH_INTERVAL
    global GCODE_VIEW_SPEED
    global LOAD_INTERVAL
    global MAX_LOAD_LINES
    global BLOCK_SIZE
    global BLOCK_HEADER_SIZE

    global FW_UPD_ADDRESS
    global CTL_UPD_ADDRESS
    global DOWNLOAD_ADDRESS

    global LANGS

    FW_UPD_ADDRESS = 'https://raw.githubusercontent.com/carvera-community/carvera_community_firmware/master/version.txt'
    CTL_UPD_ADDRESS = 'https://raw.githubusercontent.com/carvera-community/carvera_controller/main/CHANGELOG.md'
    DOWNLOAD_ADDRESS = 'https://github.com/carvera-community/carvera_controller/releases/latest'

    LANGS = {
        'en': 'English',
        'zh-CN': '中文简体(Simplified Chinese)',
    }

    SHORT_LOAD_TIMEOUT = 3  # s
    WIFI_LOAD_TIMEOUT = 30  # s
    HEARTBEAT_TIMEOUT = 10

    MAX_TOUCH_INTERVAL = 0.15
    GCODE_VIEW_SPEED = 1

    LOAD_INTERVAL = 10000  # must be divisible by MAX_LOAD_LINES
    MAX_LOAD_LINES = 10000

    1  # 定义块大小
    BLOCK_SIZE = 4096
    BLOCK_HEADER_SIZE = 4


def main():
    if is_android():
        android_tweaks()

    # load the global constants
    load_constants()

    # Language translation needs to be globally accessiable
    global default_lang
    global tr
    global HALT_REASON
    default_lang = init_lang()
    tr = Lang(default_lang)
    set_config_defaults(default_lang)
    load_app_configs()
    HALT_REASON = load_halt_translations(tr)

    base_path = app_base_path()
    register_fonts(base_path)
    register_images(base_path)
    MakeraApp().run()


if __name__ == '__main__':
    main()
