import copy

from carveracontroller.addons.probing.operations.ProbeTip.ProbeTipParameterDefinitions import \
    ProbeTipParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions


class ProbeTipOperationBore(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        if self.requires_x:
            config[ProbeTipParameterDefinitions.YAxisDistance.code] = ''
        if self.requires_y:
            config[ProbeTipParameterDefinitions.XAxisDistance.code] = ''

        super().apply_direction(ProbeTipParameterDefinitions.ProbeDepth.code,
                        config,
                        self.invert_direction)                    

        return "M460.1" + self.config_to_gcode(config)


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = ProbeTipParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = ProbeTipParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition

        required_definitions = {name: value for name, value in ProbeTipParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

class ProbeTipOperationBoss(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        if self.requires_x:
            config[ProbeTipParameterDefinitions.YAxisDistance.code] = ''
        if self.requires_y:
            config[ProbeTipParameterDefinitions.XAxisDistance.code] = ''

        super().apply_direction(ProbeTipParameterDefinitions.ProbeDepth.code,
                        config,
                        self.invert_direction)                    

        return "M460.2" + self.config_to_gcode(config)


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = ProbeTipParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = ProbeTipParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition

        required_definitions = {name: value for name, value in ProbeTipParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

class ProbeTipOperationAnchor(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        if self.requires_x:
            config[ProbeTipParameterDefinitions.YAxisDistance.code] = ''
        if self.requires_y:
            config[ProbeTipParameterDefinitions.XAxisDistance.code] = ''

        super().apply_direction(ProbeTipParameterDefinitions.ProbeDepth.code,
                        config,
                        self.invert_direction)                    

        return "M460.3" + self.config_to_gcode(config)


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = ProbeTipParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = ProbeTipParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition

        required_definitions = {name: value for name, value in ProbeTipParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

