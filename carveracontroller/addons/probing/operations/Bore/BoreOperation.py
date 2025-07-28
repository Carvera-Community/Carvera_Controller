import copy

from carveracontroller.addons.probing.operations.Bore.BoreParameterDefinitions import \
    BoreParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions


class BoreOperation(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        if not self.requires_x:
             config[BoreParameterDefinitions.XAxisDistance.code] = ''
        if not self.requires_y:
             config[BoreParameterDefinitions.YAxisDistance.code] = ''     

        return "M461" + self.config_to_gcode(config)


    def get_missing_config(self, config: dict[str, float]):
        if self.requires_x:
            definition = BoreParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = BoreParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition
            
        required_definitions = {name: value for name, value in BoreParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}

        return super().validate_required(required_definitions, config)

