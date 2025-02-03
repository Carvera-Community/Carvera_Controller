from kivy.uix.boxlayout import BoxLayout

from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerParameterDefinitions import \
    InsideCornerParameterDefinitions


class InsideCornerSettings(BoxLayout):

    config = {}
    def __init__(self, **kwargs):
        super(InsideCornerSettings, self).__init__(**kwargs)

    def setting_changed(self, key: str, value: float):
        param = getattr(InsideCornerParameterDefinitions, key, None)
        if param is None:
            raise KeyError(f"Invalid key '{key}'")

        self.config[param.GCodeParam] = value

    def get_config(self):
        return self.config;