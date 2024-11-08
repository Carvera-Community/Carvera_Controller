import sys
from kivy.app import App
from kivy.uix.floatlayout import FloatLayout
from kivy.factory import Factory
from kivy.properties import ObjectProperty
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView

from CNC import CNC

class RV(RecycleView):
    def __init__(self, **kwargs):
        super(RV, self).__init__(**kwargs)

class LoadDialog(FloatLayout):
    load = ObjectProperty(None)
    cancel = ObjectProperty(None)

class GcodeParser(FloatLayout):
    loadfile = ObjectProperty(None)

    def __init__(self):
        super(GcodeParser, self).__init__()

        self.cnc = CNC()

    def dismiss_popup(self):
        self._popup.dismiss()

    def show_load(self):
        content = LoadDialog(load=self.load, cancel=self.dismiss_popup)
        self._popup = Popup(title="Load gcode file", content=content,
                            size_hint=(0.8, 0.8))
        self._popup.open()

    def load(self, path, filename):
        try:
            f = open(filename[0], "r")
        except:
            print(sys.exc_info()[1])
            return
        self.rv_origin.data = []
        self.rv_parser.data = []

        self.cnc.init()
        line_no = 1
        for line in f:
            line_txt = line[:-1].replace("\x0d", "")
            self.cnc.parseLine(line_txt, line_no)
            self.rv_origin.data.append({'text': str(line_no).ljust(12) + line_txt.strip()})
            line_no += 1

        line_no = 1
        for block in self.cnc.blocks:
            for i, path in enumerate(block[1]):
                self.rv_parser.data.append({'text': str(line_no).ljust(12) + 'X: {} Y: {} Z: {} A: {} Color: {} Line: {} Tool: {}'.format(
                    path[0],
                    path[1],
                    path[2],
                    path[3],
                    'Red' if path[4] else 'Green',
                    path[5],
                    block[0])})
                line_no += 1

        f.close()
        self.dismiss_popup()

class GcodeParserApp(App):
    def build(self):
        return GcodeParser()

if __name__ == '__main__':
    GcodeParserApp().run()