from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerParameterDefinitions import \
    OutsideCornerParameterDefinitions


class OutsideCornerOperation(OperationsBase):
    title: str
    image_path: str
    description: str
    imagePath: str

    def __init__(self, title, from_right, from_bottom, image_path, **kwargs):
        self.title = title
        self.image_path = image_path
        self.from_right = from_right
        self.from_bottom = from_bottom

    def generate(self, config: dict[str, float]):

        if OutsideCornerParameterDefinitions.XAxisDistance.code in config and self.from_right:
            config[OutsideCornerParameterDefinitions.XAxisDistance.code] = config[
                                                                               OutsideCornerParameterDefinitions.XAxisDistance.code] * -1

        if OutsideCornerParameterDefinitions.YAxisDistance.code in config and self.from_bottom:
            config[OutsideCornerParameterDefinitions.YAxisDistance.code] = config[
                                                                               OutsideCornerParameterDefinitions.YAxisDistance.code] * -1

        return "M464 " + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]) -> ProbeSettingDefinition | None:

        required_definitions = {name: value for name, value in OutsideCornerParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}

        return super().validate_required(required_definitions, config)
