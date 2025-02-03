from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerParameterDefinitions import \
    InsideCornerParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase


class InsideCornerOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, from_right, from_bottom, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.from_right = from_right
        self.from_bottom = from_bottom

    def generate(self, config: dict[str, float]):

        if InsideCornerParameterDefinitions.XAxisDistance.GCodeParam in config and self.from_right:
            config[InsideCornerParameterDefinitions.XAxisDistance.GCodeParam] = config[InsideCornerParameterDefinitions.XAxisDistance.GCodeParam] * -1

        if InsideCornerParameterDefinitions.YAxisDistance.GCodeParam in config and self.from_bottom:
            config[InsideCornerParameterDefinitions.YAxisDistance.GCodeParam] = config[InsideCornerParameterDefinitions.YAxisDistance.GCodeParam] * -1

        return "M463 " + self.config_to_gcode(config)
