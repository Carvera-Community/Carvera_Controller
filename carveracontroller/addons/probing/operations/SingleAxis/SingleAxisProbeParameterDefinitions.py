from carveracontroller.addons.probing.operations.OperationsBase import ProbeSettingDefinition


# M466
# X{dist} Y{dist} Z{dist} D{tip diameter}  Q{angle} L{repeats} R{retract}
# S{save as xy, if only 1 axis is given with no q, then will only save that axis as zero}
# F{feed rate} I{invert for NC}

class SingleAxisProbeParameterDefinitions:
    XAxisDistance = ProbeSettingDefinition("X", "X Distance", False, "X distance along the particular axis to probe.")

    YAxisDistance = ProbeSettingDefinition("Y", "Y Distance", False, "Y distance along the particular axis to probe.")

    ZAxisDistance = ProbeSettingDefinition("Z", "Z Distance", False, "Z distance along the particular axis to probe.")

    ProbeTipDiameter = ProbeSettingDefinition('D', "Tip Dia", False, "Probe Tip Diameter, stored in config")

    QAngle = ProbeSettingDefinition('Q', "Angle", False, "TODO: need docs")

    FastFeedRate = ProbeSettingDefinition('F', "FF Rate", False, "optional fast feed rate override")

    RepeatOperationCount = ProbeSettingDefinition('L', "Repeat", False,
                                                  "setting L to 1 will repeat the entire probing operation from the newly found center point")

    EdgeRetractDistance = ProbeSettingDefinition('R', "Edge Retract", False,
                                                 "changes the retract distance from the edge of the pocket for the double tap probing")

    ZeroXYPosition = ProbeSettingDefinition('S', "ZeroXY", False, "save corner position as new WCS Zero in X and Y")


    UseProbeNormallyClosed = ProbeSettingDefinition('I', "NC", False, "Probe is normally closed")
