# M465.1 - Probe 4th Axis (A-Axis) Stock
# https://carvera-community.gitbook.io/docs/firmware/supported-commands/mcodes/probing#m465.1-probe-4th-axis-a-axis-stock
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition


class FourthAxisParameterDefinitions:
    YTotalDistance = ProbeSettingDefinition(
        "Y", "Y Probing Distance", True,
        "Total probing distance; machine moves to +Y/2 and -Y/2 from current position."
    )
    ProbeHeight = ProbeSettingDefinition(
        "H", "Probe Height", True,
        "Distance to probe down from current position."
    )
    FeedRate = ProbeSettingDefinition("F", "Feed Rate", False, "Feed rate for probing (mm/min).")
    RapidFeedRate = ProbeSettingDefinition("K", "Rapid Rate", False, "Rapid feed rate for positioning (mm/min).")
    RepeatCount = ProbeSettingDefinition("L", "Repeat", False, "Number of probe cycles to repeat.")
    RetractDistance = ProbeSettingDefinition("R", "Retract", False, "Retract distance from touched surface (mm).")
    RotateAfterProbe = ProbeSettingDefinition("V", "Rotate A after probe", False, "Rotate A axis after probing")
    SaveAOffset = ProbeSettingDefinition("S", "Save A offset", False, "Save the A axis offset after probing",)
