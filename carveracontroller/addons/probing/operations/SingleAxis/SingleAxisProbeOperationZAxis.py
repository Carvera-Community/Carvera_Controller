import copy

from docutils.nodes import definition

from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition


class SingleAxisProbeOperationZAxis(OperationsBase):
    imagePath: str

    def __init__(self, title, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        # remove other axes for clarity
        config[SingleAxisProbeParameterDefinitions.XAxisDistance.code] = ''
        config[SingleAxisProbeParameterDefinitions.YAxisDistance.code] = ''

        super().apply_direction(SingleAxisProbeParameterDefinitions.ZAxisDistance.code,
                                config,
                                True)

        return "M466 " + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]):

        print(config)
        definition = SingleAxisProbeParameterDefinitions.ZAxisDistance
        if not definition.code in config:
            return definition
        elif len(config[definition.code]) == 0:
            return definition
        return None
