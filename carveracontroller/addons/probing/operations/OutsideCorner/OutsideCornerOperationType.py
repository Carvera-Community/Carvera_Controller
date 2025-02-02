from enum import Enum
from carveracontroller.addons.probing.operations.OutsideCorner.OutsideCornerOperation import OutsideCornerOperation

class OutsideCornerOperationType(Enum):
    TopLeft = OutsideCornerOperation("Top Left", False, False, "")
    TopRight = OutsideCornerOperation("Top Right", True, False, "")
    BottomRight = OutsideCornerOperation("Bottom Right", True, True, "")
    BottomLeft = OutsideCornerOperation("Bottom Left", False, False, "")
