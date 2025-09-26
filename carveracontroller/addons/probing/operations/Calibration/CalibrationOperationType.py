from enum import Enum
from carveracontroller.addons.probing.operations.Calibration.CalibrationOperation import CalibrationOperationFourthY
from carveracontroller.addons.probing.operations.Calibration.CalibrationOperation import CalibrationOperationFourthZ
from carveracontroller.addons.probing.operations.Calibration.CalibrationOperation import CalibrationOperationAnchor1
from carveracontroller.addons.probing.operations.Calibration.CalibrationOperation import CalibrationOperationAnchor2

class CalibrationOperationType(Enum):
    FourthY = CalibrationOperationFourthY("Calibration - FourthY", False, False,False, "")
    FourthZ = CalibrationOperationFourthZ("Calibration - FourthZ", True, False,False, "")
    Anchor1 = CalibrationOperationAnchor1("Calibration - Anchor1", False, False,False, "")
    Anchor2 = CalibrationOperationAnchor2("Calibration - Anchor1", False, False,False, "")
