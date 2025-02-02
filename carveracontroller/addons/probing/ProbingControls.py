from kivy.uix.gridlayout import GridLayout
from kivy.properties import StringProperty

class ProbeSettingLabel(GridLayout):
    label_text = StringProperty("")
    hint_text = StringProperty("")
    # setting_key = StringProperty("")
