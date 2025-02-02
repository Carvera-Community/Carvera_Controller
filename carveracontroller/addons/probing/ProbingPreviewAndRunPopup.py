from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.ProbeGcodeGenerator import ProbeGcodeGenerator
# from carveracontroller.Controller import Controller
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants

class ProbingPreviewAndRunPopup(ModalView):
    def __init__(self, config, **kwargs):
        self.config = config
        # self.controller = controller
        super(ProbingPreviewAndRunPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        if self.cb_probe_normally_closed.active:
            return ProbingConstants.switch_type_nc

        if self.cb_probe_normally_open.active:
            return ProbingConstants.switch_type_no

        return 0

    # def on_minus_y(self):
    #     self.root.start_probing(txt_x.text, txt_y.text, txt_z.text, txt_a.text, root.get_probe_switch_type())

    def start_probing(self, x, y, z, a, switch_type):
        gcode = ProbeGcodeGenerator(x, y, z, a, switch_type)
        print(gcode)
        if len(gcode) > 0:
            self.controller.executeCommand(gcode + "\n")
