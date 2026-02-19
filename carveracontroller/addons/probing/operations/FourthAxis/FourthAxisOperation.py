from carveracontroller.addons.probing.operations.FourthAxis.FourthAxisParameterDefinitions import (
    FourthAxisParameterDefinitions,
)
from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition


class FourthAxisOperation(OperationsBase):
    """M465.1 - Probe 4th Axis (A-Axis) stock to determine angular position."""

    def __init__(self, title, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path

    def generate(self, input_config: dict[str, float]) -> str:
        config = {k: str(v) for k, v in input_config.items()}
        return "M465.1 " + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, float]):
        required = {
            name: value
            for name, value in FourthAxisParameterDefinitions.__dict__.items()
            if isinstance(value, ProbeSettingDefinition) and value.is_required
        }
        return super().validate_required(required, config)
