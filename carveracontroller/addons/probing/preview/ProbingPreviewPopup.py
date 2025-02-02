from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbingOptions


class ProbingPreviewPopup(ModalView):
    title = StringProperty('Probing Preview')
    probe_preview_label = StringProperty('N/A')
    operation: OperationsBase
    gcode: str

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

        # if len(gcode) > 0:
        #     self.controller.executeCommand(gcode + "\n")

    def update_operation(self, operation: OperationsBase, config):
        self.operation = operation
        gcode = self.get_gcode(config)
        if len(gcode) > 0:
            self.probe_preview_label = gcode
        else:
            self.probe_preview_label = "N/A"

    def get_gcode(self, config):
        config[ProbingOptions.UseProbeNormallyClosed] = self.get_probe_switch_type()
        gcode = self.operation.value.generate(config)
        return gcode
