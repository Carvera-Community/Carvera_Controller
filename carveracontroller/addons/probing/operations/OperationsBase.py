from abc import abstractmethod

class OperationsBase():
    def __init__(self, value):
        self.value = value

    @abstractmethod
    def generate(self, config: dict[str, float]) -> str:
        pass

    def config_to_gcode(self, config: dict[str, float]) -> str:
        return " " + ' '.join([f'{key}{value} ' for key, value in config.items()])


class ProbeSettingDefinition:
    GCodeParam:str
    Description:str

    def __init__(self, g_code_param:str, label:str, description:str):
        self.label = label
        self.GCodeParam = g_code_param
        self.Description = description


class ProbingOptions:

    # Specify 1 for a Probe that is normally closed, otherwise
    UseProbeNormallyClosed = 'I'