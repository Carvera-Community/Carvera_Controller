# Docs: https://github.com/Carvera-Community/Carvera_Community_Firmware/blob/master/tests/TEST_ProbingM460toM465/TEST_ProbingM460toM465_readme.txt
from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition


class InsideCornerParameterDefinitions:
    XAxisDistance = ProbeSettingDefinition("X", "X Dis", "X distance along the particular axis to probe.")

    YAxisDistance = ProbeSettingDefinition("Y", "X Dis", "Y distance along the particular axis to probe.")

    PocketProbeDepth = ProbeSettingDefinition('H', "Pocket Depth",
                                              "Optional parameter, if set the probe will probe down by "
                                              "this value to find the pocket bottom and then retract slightly "
                                              "before probing the sides of the bore. Useful for shallow pockets")

    FastFeedRate = ProbeSettingDefinition('F', "FF Rate", "optional fast feed rate override")

    RapidFeedRate = ProbeSettingDefinition('K', "Rapid", "optional rapid feed rate override")

    RepeatOperationCount = ProbeSettingDefinition('L', "Repeat",
                                                  "setting L to 1 will repeat the entire probing operation from the newly found center point")

    EdgeRetractDistance = ProbeSettingDefinition('R', "Edge Retract",
                                                 "changes the retract distance from the edge of the pocket for the double tap probing")

    BottomSurfaceRetract = ProbeSettingDefinition('C', "Btm Retract",
                                                  "optional parameter, if H is enabled and the probe happens, this is how far to retract off the bottom surface of the part. Defaults to 2mm")

    ZeroXYPosition = ProbeSettingDefinition('S', "ZeroXY", "save corner position as new WCS Zero in X and Y")

    ProbeTipDiameter = ProbeSettingDefinition('D', "Tip Dia", "Probe Tip Diameter, stored in config")

    ProbeDepth = ProbeSettingDefinition('E', "Depth",
                                        "how far below the top surface of the model to move down in order to probe on each side")
