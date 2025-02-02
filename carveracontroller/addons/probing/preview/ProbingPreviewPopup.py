from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.ProbeGcodeGenerator import ProbeOperation, M464Params
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants


class ProbingPreviewPopup(ModalView):
    title = StringProperty('Probing Preview')
    probe_preview_label = StringProperty('N/A')

    def __init__(self, config, controller, **kwargs):
        self.operation = None
        self.config = config
        self.controller = controller
        super(ProbingPreviewPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        return ProbingConstants.switch_type_nc
        # if self.cb_probe_normally_closed.active:
        #     return ProbingConstants.switch_type_nc
        #
        # if self.cb_probe_normally_open.active:
        #     return ProbingConstants.switch_type_no

        return 0

    def start_probing(self, x, y, z, a, switch_type):
        if self.operation is None:
            return

        print("start probing")

        # print(gcode)
        # if len(gcode) > 0:
        #     self.controller.executeCommand(gcode + "\n")

    def update_operation(self, operation: ProbeOperation, config):
        self.operation = operation
        config[M464Params.UseProbeNormallyClosed] = self.get_probe_switch_type()

        gcode = operation.value.generate(config)
        if len(gcode) > 0:
            self.probe_preview_label = gcode
        else:
            self.probe_preview_label = "N/A"
