from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.FourthAxis.FourthAxisParameterDefinitions import (
    FourthAxisParameterDefinitions,
)


class FourthAxisSettings(BoxLayout):
    config_filename = "fourth-axis-settings.json"
    config = {}

    def __init__(self, **kwargs):
        self.config = ConfigUtils.load_config(self.config_filename)
        self.config = self.order_config(self.config)
        super(FourthAxisSettings, self).__init__(**kwargs)

    def setting_changed(self, key: str, value: str):
        param = getattr(FourthAxisParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value
        self.config = self.order_config(self.config)
        ConfigUtils.save_config(self.config, self.config_filename)

    def order_config(self, config: dict) -> dict:
        order = ["Y", "H", "F", "K", "L", "R", "V", "S"]
        temp_config = {}
        for key in order:
            if key in config:
                temp_config[key] = config[key]
        return temp_config

    def get_setting(self, key: str) -> str:
        param = getattr(FourthAxisParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")
        if param.code in self.config:
            return str(self.config[param.code])
        self.setting_changed(key, param.default)
        return param.default

    def get_config(self):
        return {k: str(v) for k, v in self.config.items()}
