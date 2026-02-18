from enum import Enum

from carveracontroller.addons.probing.operations.FourthAxis.FourthAxisOperation import (
    FourthAxisOperation,
)


class FourthAxisOperationType(Enum):
    Level = FourthAxisOperation(
        "4th Axis Level",
        "addons/probing/data/icons_1024x768/calibration/Calibrate_4th_Axis_Level_02.png",
    )
