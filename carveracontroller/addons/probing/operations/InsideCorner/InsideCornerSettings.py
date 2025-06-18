from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerParameterDefinitions import \
    InsideCornerParameterDefinitions


class InsideCornerSettings(BoxLayout):
    config_filename = "inside-corner-settings.json"
    config = {}

    def __init__(self, **kwargs):
        self.config = ConfigUtils.load_config(self.config_filename)
        super(InsideCornerSettings, self).__init__(**kwargs)

    def setting_changed(self, key: str, value: float):
        # Hacky code to translate between key/value of Kivy Spinner
        if key == 'ZeroXYPosition':
            if value == 'Disabled':
                value = "0"
            elif value == 'X/Y':
                value = "1"
            elif value == 'X/Y/Z':
                value = "2"

        param = getattr(InsideCornerParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value
        ConfigUtils.save_config(self.config, self.config_filename)

    def get_setting(self, key: str) -> str:
        param = getattr(InsideCornerParameterDefinitions, key, None)

        # Hacky code to translate between key/value of Kivy Spinner
        if key == "ZeroXYPosition" and self.config.get("S"):
            if self.config["S"] == '0':
                return 'Disabled'
            elif self.config["S"] == '1':
                return 'X/Y'
            elif self.config["S"] == '2':
                return 'X/Y/Z'
        
        return str(self.config[param.code] if param.code in self.config else "")

    def get_config(self):
        return self.config
