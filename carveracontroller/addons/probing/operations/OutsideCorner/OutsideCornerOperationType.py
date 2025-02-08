from enum import Enum
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperation import OutsideCornerOperation

class OutsideCornerOperationType(Enum):
    TopLeft = OutsideCornerOperation("Outside Corner - Top Left", False, True, "")
    TopRight = OutsideCornerOperation("Outside Corner - Top Right", True, True, "")
    BottomRight = OutsideCornerOperation("Outside Corner - Bottom Right", True, False, "")
    BottomLeft = OutsideCornerOperation("Outside Corner - Bottom Left", False, False, "")
