from kivy.uix.boxlayout import BoxLayout
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerParameterDefinitions import OutsideCornerParameterDefinitions

class OutsideCornerSettings(BoxLayout):
    config_filename = "outside-corner-settings.json"
    config = {}

    def __init__(self, **kwargs):
        super(OutsideCornerSettings, self).__init__(**kwargs)
        self.config = ConfigUtils.load_config(self.config_filename)

    def setting_changed(self, key: str, value: float):
        param = getattr(OutsideCornerParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value
        self.config = self.order_config(self.config)
        ConfigUtils.save_config(self.config, self.config_filename)

    def order_config(self, config: dict[str, float]):
        order = ["X", "Y", "J", "D", "H", "F", "K", "L", "R", "C", "Q", "E", "S", "I"]
        temp_config = {}
        for key in order:
            if key in config:
                temp_config[key] = config[key]
        return temp_config

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

        return self.config
