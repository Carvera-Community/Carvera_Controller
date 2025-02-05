from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerParameterDefinitions import OutsideCornerParameterDefinitions


class OutsideCornerSettings(BoxLayout):

    config = {}
    def __init__(self, **kwargs):
        super(OutsideCornerSettings, self).__init__(**kwargs)

    def setting_changed(self, key: str, value: float):
        param = getattr(OutsideCornerParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.code] = value

    def get_setting(self, key:str):
        param = getattr(OutsideCornerParameterDefinitions, key, None)
        if key not in self.config:
            return None
        return self.config[param.code]

    def get_config(self):
        return self.config;