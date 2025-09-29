from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.recycleboxlayout import RecycleBoxLayout
from kivy.uix.behaviors import FocusBehavior
from kivy.uix.recycleview.layout import LayoutSelectionBehavior

import logging
logger = logging.getLogger(__name__)

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase

class ProbingPreviewPopup(ModalView):
    title = StringProperty('Confirm')
    probe_preview_label = StringProperty('N/A')
    config: dict[str, float]
    gcode = StringProperty("")


    def __init__(self, controller, **kwargs):
        self.controller = controller
        super(ProbingPreviewPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        return 1
        # if self.cb_probe_normally_closed.active:
        #     return ProbingConstants.switch_type_nc
        #
        # if self.cb_probe_normally_open.active:
        #     return ProbingConstants.switch_type_no

    def  start_probing(self):
        if len(self.gcode) > 0:
            logger.debug("running gcode: " + self.gcode)
            self.controller.executeCommand(self.gcode + "\n")
        else:
            logger.error("no gcode")

class PopupMDI(RecycleView):

    def __init__(self, **kwargs):
        super(PopupMDI, self).__init__(**kwargs)