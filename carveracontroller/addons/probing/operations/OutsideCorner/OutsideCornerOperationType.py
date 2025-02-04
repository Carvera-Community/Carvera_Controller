from enum import Enum
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperation import OutsideCornerOperation

class OutsideCornerOperationType(Enum):
    TopLeft = OutsideCornerOperation("Outside Corner - Top Left", False, False, "")
    TopRight = OutsideCornerOperation("Outside Corner - Top Right", True, False, "")
    BottomRight = OutsideCornerOperation("Outside Corner - Bottom Right", True, True, "")
    BottomLeft = OutsideCornerOperation("Outside Corner - Bottom Left", False, False, "")
