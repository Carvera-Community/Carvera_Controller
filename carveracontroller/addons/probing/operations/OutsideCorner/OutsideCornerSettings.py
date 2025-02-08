from kivy.properties import ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerParameterDefinitions import OutsideCornerParameterDefinitions
from kivy.clock import Clock

class OutsideCornerSettings(BoxLayout):
    config_filename = "outside-corner-settings.json"
    config = {}

    def __init__(self, **kwargs):
        print('init outside corner settings')
        super(OutsideCornerSettings, self).__init__(**kwargs)
        self.config = ConfigUtils.load_config(self.config_filename)

    def setting_changed(self, key: str, value: float):
        param = getattr(OutsideCornerParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value
        ConfigUtils.save_config(self.config, self.config_filename)


    def get_setting(self, key: str) -> str:
        param = getattr(OutsideCornerParameterDefinitions, key, None)
        return str(self.config[param.code] if param.code in self.config else "")

    def get_config(self):
        required_parameters = {name: value for name, value in OutsideCornerParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition)}

        for name, param in required_parameters.items():
            control = self.ids.get(name, None)
            if control:
                if isinstance(control, TextInput):
                    self.config[param.code] = control.text
                    print(param.code + " = " + control.text)
                elif isinstance(control, Switch):
                    self.config[param.code] = "1" if control.active else ""
            else:
                print("no control with name: " + name)

        return self.config;