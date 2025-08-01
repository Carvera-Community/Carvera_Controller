# Docs: https://github.com/Carvera-Community/Carvera_Community_Firmware/blob/master/tests/TEST_ProbingM460toM465/TEST_ProbingM460toM465_readme.txt
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition


class BossParameterDefinitions:
    XAxisDistance = ProbeSettingDefinition("X", "X Distance", False, "Boss Diameter in X.")

    YAxisDistance = ProbeSettingDefinition("Y", "Y Distance", False, "Boss Diameter in Y.")

    PocketProbeDepth = ProbeSettingDefinition('H', "Pocket Depth", False,
                                              "Optional parameter, if set the probe will probe down by "
                                              "this value to find the pocket bottom and then retract slightly "
                                              "before probing the sides of the Boss. Useful for shallow pockets")

    FastFeedRate = ProbeSettingDefinition('F', "FF Rate", False, "optional fast feed rate override")

    RapidFeedRate = ProbeSettingDefinition('K', "Rapid", False, "optional rapid feed rate override")

    RepeatOperationCount = ProbeSettingDefinition('L', "Repeat", False,
                                                  "setting L to 1 will repeat the entire probing operation from the newly found center point")

    EdgeRetractDistance = ProbeSettingDefinition('R', "Edge Retract", False,
                                                 "changes the retract distance from the edge of the pocket for the double tap probing")

    QAngle = ProbeSettingDefinition('Q', "Angle", False, "TODO: need docs")

    BottomSurfaceRetract = ProbeSettingDefinition('C', "Btm Retract", False,
                                                  "optional parameter, if H is enabled and the probe happens, this is how far to retract off the bottom surface of the part. Defaults to 2mm")

    ZeroXYPosition = ProbeSettingDefinition('S', "ZeroXY", False, "save corner position as new WCS Zero in X and Y")

    ProbeTipDiameter = ProbeSettingDefinition('D', "Tip Dia", False, "Probe Tip Diameter, stored in config")

    ProbeDepth = ProbeSettingDefinition('E', "Depth", False,
                                        "how far below the top surface of the model to move down in order to probe on each side")

    UseProbeNormallyClosed = ProbeSettingDefinition('I', "NC", False, "Probe is normally closed")
    
    ProbeClearance = ProbeSettingDefinition('J', "Probe Clearance", False, "When Probing a boss, this is added to the X and Y values when moving outside the boss")
