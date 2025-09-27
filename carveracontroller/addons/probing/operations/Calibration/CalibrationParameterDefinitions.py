# Docs: https://github.com/Carvera-Community/Carvera_Community_Firmware/blob/master/tests/TEST_ProbingM460toM465/TEST_ProbingM460toM465_readme.txt
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition


class CalibrationParameterDefinitions:
    XAxisDistance = ProbeSettingDefinition("X", "X Distance", False, "X distance along the particular axis to probe.")

    YAxisDistance = ProbeSettingDefinition("Y", "Y Distance", False, "Y distance along the particular axis to probe.")

    PocketProbeDepth = ProbeSettingDefinition('H', "Pocket Depth", False,
                                              "Optional parameter, if set the probe will probe down by "
                                              "this value to find the pocket bottom and then retract slightly "
                                              "before probing the sides of the Calibration. Useful for shallow pockets")

    PinDiameter = ProbeSettingDefinition('R', "Pin Diameter", False, "")

    ZeroXYPosition = ProbeSettingDefinition('S', "ZeroXY", False, "save corner position as new WCS Zero in X and Y")

    ProbeTipDiameter = ProbeSettingDefinition('D', "Tip Dia", False, "Probe Tip Diameter, stored in config")

    UseProbeNormallyClosed = ProbeSettingDefinition('I', "NC", False, "Probe is normally closed")
