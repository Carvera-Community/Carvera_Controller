from kivy.properties import StringProperty
from kivy.uix.modalview import ModalView

from carveracontroller.addons.probing.ProbeGcodeGenerator import ProbeGcodeGenerator
from carveracontroller.addons.probing.ProbingConstants import ProbingConstants

class ProbingPreviewPopup(ModalView):
    title = StringProperty('Probing Preview')

    def __init__(self, config, controller, **kwargs):
        self.config = config
        self.controller = controller
        super(ProbingPreviewPopup, self).__init__(**kwargs)

    def get_probe_switch_type(self):
        if self.cb_probe_normally_closed.active:
            return ProbingConstants.switch_type_nc

        if self.cb_probe_normally_open.active:
            return ProbingConstants.switch_type_no

        return 0

    def start_probing(self, x, y, z, a, switch_type):
        gcode = ProbeGcodeGenerator(x, y, z, a, switch_type)
        print(gcode)
        if len(gcode) > 0:
            self.controller.executeCommand(gcode + "\n")

    def update_preview(self):
        switch_type = self.get_probe_switch_type();
        generator = ProbeGcodeGenerator()
        gcode = generator.get_straight_probe(self.txt_x.text, self.txt_y.text, self.txt_z.text, self.txt_a.text,
                                             switch_type)
        if len(gcode) > 0:
            self.probe_preview_label.text = gcode
        else:
            self.probe_preview_label.text = "N/A"