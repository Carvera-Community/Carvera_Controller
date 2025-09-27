import copy

from carveracontroller.addons.probing.operations.Calibration.CalibrationParameterDefinitions import \
    CalibrationParameterDefinitions
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import \
    SingleAxisProbeParameterDefinitions


class CalibrationOperationFourthY(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        config[CalibrationParameterDefinitions.XAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.PinDiameter.code] = ''      

        return "M469.4 " + self.config_to_gcode(config) + "\n Make sure 4th Axis and 3 axis probe are installed"


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = CalibrationParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = CalibrationParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition
            
        required_definitions = {name: value for name, value in CalibrationParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

class CalibrationOperationFourthZ(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        config[CalibrationParameterDefinitions.YAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.PinDiameter.code] = '' 
               

        return "M469.5 " + self.config_to_gcode(config) + "\n Make sure 4th Axis in on has a pin in the chuck" 


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = CalibrationParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = CalibrationParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition
            
        required_definitions = {name: value for name, value in CalibrationParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

class CalibrationOperationAnchor1(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        config[CalibrationParameterDefinitions.YAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.XAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.PinDiameter.code] = ''  
        config[CalibrationParameterDefinitions.PocketProbeDepth.code] = ''                   

        return "M469.1" + self.config_to_gcode(config)+ "\n Make sure Anchor 1 and 3 axis probe are installed" 


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = CalibrationParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = CalibrationParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition

        required_definitions = {name: value for name, value in CalibrationParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)


class CalibrationOperationAnchor2(OperationsBase):
    imagePath: str

    def __init__(self, title, requires_x, requires_y,invert_direction, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.requires_x = requires_x
        self.requires_y = requires_y
        self.invert_direction = invert_direction

    def generate(self, input_config: dict[str, float]):

        config = copy.deepcopy(input_config)

        config[CalibrationParameterDefinitions.YAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.XAxisDistance.code] = ''
        config[CalibrationParameterDefinitions.PinDiameter.code] = ''
        config[CalibrationParameterDefinitions.PocketProbeDepth.code] = ''            

        return "M469.2" + self.config_to_gcode(config) + "\n Make sure Anchor 2 and 3 axis probe are installed" 


    def get_missing_config(self, config: dict[str, float]):
        
        if self.requires_x:
            definition = CalibrationParameterDefinitions.XAxisDistance
            if not definition.code in config:
                return definition
        if self.requires_y:
            definition = CalibrationParameterDefinitions.YAxisDistance
            if not definition.code in config:
                return definition

        required_definitions = {name: value for name, value in CalibrationParameterDefinitions.__dict__.items()
                                if isinstance(value, ProbeSettingDefinition) and value.is_required}




        return super().validate_required(required_definitions, config)

