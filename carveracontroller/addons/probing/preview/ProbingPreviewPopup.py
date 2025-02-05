from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase

class ProbingPreviewPopup(ModalView):
    title = StringProperty('Confirm')
    probe_preview_label = StringProperty('N/A')
    operation: OperationsBase
    config: dict[str, float]
    gcode = StringProperty("")

    def __init__(self, controller, **kwargs):
        self.operation = None
        self.controller = controller
        super(ProbingPreviewPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        return 1
        # if self.cb_probe_normally_closed.active:
        #     return ProbingConstants.switch_type_nc
        #
        # if self.cb_probe_normally_open.active:
        #     return ProbingConstants.switch_type_no
        return 0

    def start_probing(self):
        if self.operation is None:
            return
        if len(self.gcode) > 0:
            self.controller.executeCommand(self.gcode + "\n")