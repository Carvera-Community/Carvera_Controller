"""Compact File/MDI tab for the File workspace command pane."""

from kivy.factory import Factory
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.tooltips.Tooltips import ToolTipButton


class CmdPaneTab(BoxLayout, ToolTipButton):
    selected = BooleanProperty(False)
    tab_text = StringProperty("")
    icon = StringProperty("")


if "CmdPaneTab" not in Factory.classes:
    Factory.register("CmdPaneTab", cls=CmdPaneTab)
