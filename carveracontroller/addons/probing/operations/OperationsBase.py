from abc import abstractmethod


class OperationsBase():
    title: str = ""

    def __init__(self, value):
        self.title = value.title
        self.value = value

    @abstractmethod
    def generate(self, config: dict[str, float]) -> str:
        pass

    def config_to_gcode(self, config: dict[str, float]) -> str:
        return " " + ' '.join([f'{key}{value} ' for key, value in config.items()])

    def validate_required(self, required_definitions, config: dict[str, float]):
        print(config)
        for name, definition in required_definitions.items():
            if not definition.code in config:
                return definition
            elif len(config[definition.code]) == 0:
                return definition

        return None


class ProbeSettingDefinition:
    code: str
    description: str
    is_required: bool

    def __init__(self, g_code_param: str, label: str, is_required: bool = False, description: str = ""):
        self.label = label
        self.code = g_code_param
        self.description = description
        self.is_required = is_required


