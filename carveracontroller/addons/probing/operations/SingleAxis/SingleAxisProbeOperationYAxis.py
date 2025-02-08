import copy

from docutils.nodes import definition

from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition


class SingleAxisProbeOperationYAxis(OperationsBase):
    imagePath: str

    def __init__(self, title, y_is_negative_move, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.y_is_negative_move = y_is_negative_move

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        # remove other axes for clarity
        config[SingleAxisProbeParameterDefinitions.XAxisDistance.code] = ''
        config[SingleAxisProbeParameterDefinitions.ZAxisDistance.code] = ''

        super().apply_direction(SingleAxisProbeParameterDefinitions.YAxisDistance.code,
                                config,
                                self.y_is_negative_move)

        return "M466 " + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]):

        definition = SingleAxisProbeParameterDefinitions.YAxisDistance
        if not definition.code in config:
            return definition
        elif len(config[definition.code]) == 0:
            return definition
        return None
