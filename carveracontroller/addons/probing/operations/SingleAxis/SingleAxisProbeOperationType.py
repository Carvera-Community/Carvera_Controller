from enum import Enum
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeOperationXAxis import \
    SingleAxisProbeOperationXAxis
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeOperationYAxis import \
    SingleAxisProbeOperationYAxis
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeOperationZAxis import \
    SingleAxisProbeOperationZAxis


class SingleAxisProbeOperationType(Enum):
    Top = SingleAxisProbeOperationYAxis("Top side (Y-)", True, "")
    Left = SingleAxisProbeOperationXAxis("Left side (X+)", False, "")
    WorkpieceTop = SingleAxisProbeOperationZAxis("Workpiece top (Z)", "")
    Right = SingleAxisProbeOperationXAxis("Right side (X-)", True, "")
    Bottom = SingleAxisProbeOperationYAxis("Bottom side (Y+)", False, "")
