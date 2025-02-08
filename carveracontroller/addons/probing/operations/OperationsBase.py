from abc import abstractmethod


class OperationsBase():
    title: str = ""

    def __init__(self, value):
        self.title = value.title
        self.value = value

    @abstractmethod
    def generate(self, config: dict[str, float]) -> str:
        pass

    def config_to_gcode(self, config: dict[str, str]) -> str:
        return " " + ' '.join([f'{key}{value}' for key, value in config.items() if value.strip() != ""])

    def validate_required(self, required_definitions, config: dict[str, float]):
        print(config)
        for name, definition in required_definitions.items():
            if not definition.code in config:
                return definition
            elif len(config[definition.code]) == 0:
                return definition
        return None

    def apply_direction(self, key, config: dict[str, float], is_opposite: bool):
        if key in config and is_opposite:
            # print(key + " in config and is_opposite " + str(is_opposite))
            config[key]= str(float(config[key]) * -1)

    @abstractmethod
    def get_missing_config(self, config: dict[str, float]):
       pass

class ProbeSettingDefinition:
    code: str
    description: str
    is_required: bool

    def __init__(self, g_code_param: str, label: str, is_required: bool = False, description: str = ""):
        self.label = label
        self.code = g_code_param
        self.description = description
        self.is_required = is_required


