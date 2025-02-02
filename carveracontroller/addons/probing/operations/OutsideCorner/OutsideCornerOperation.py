from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerParameterDefinitions import OutsideCornerParameterDefinitions


class OutsideCornerOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, from_right, from_bottom, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.from_right = from_right
        self.from_bottom = from_bottom

    def generate(self, config: dict[str, float]):

        if OutsideCornerParameterDefinitions.XAxisDistance.GCodeParam in config and self.from_right:
            config[OutsideCornerParameterDefinitions.XAxisDistance.GCodeParam] = config[OutsideCornerParameterDefinitions.XAxisDistance.GCodeParam] * -1

        if OutsideCornerParameterDefinitions.YAxisDistance.GCodeParam in config and self.from_bottom:
            config[OutsideCornerParameterDefinitions.YAxisDistance.GCodeParam] = config[OutsideCornerParameterDefinitions.YAxisDistance.GCodeParam] * -1

        return "M464 " + self.config_to_gcode(config)
