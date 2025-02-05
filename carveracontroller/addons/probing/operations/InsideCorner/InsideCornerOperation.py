from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerParameterDefinitions import \
    InsideCornerParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition


class InsideCornerOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, from_right, from_bottom, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.from_right = from_right
        self.from_bottom = from_bottom

    def generate(self, config: dict[str, float]):

        if InsideCornerParameterDefinitions.XAxisDistance.code in config and self.from_right:
            config[InsideCornerParameterDefinitions.XAxisDistance.code] = config[InsideCornerParameterDefinitions.XAxisDistance.code] * -1

        if InsideCornerParameterDefinitions.YAxisDistance.code in config and self.from_bottom:
            config[InsideCornerParameterDefinitions.YAxisDistance.code] = config[InsideCornerParameterDefinitions.YAxisDistance.code] * -1

        return "M463 " + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]) -> ProbeSettingDefinition | None:

        required_definitions = {name: value for name, value in InsideCornerParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}

        return super().validate_required(required_definitions, config)
