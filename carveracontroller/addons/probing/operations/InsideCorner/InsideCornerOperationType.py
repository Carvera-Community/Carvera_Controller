from enum import Enum
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperation import InsideCornerOperation

class InsideCornerOperationType(Enum):
    TopLeft = InsideCornerOperation("Top Left", False, False, "")
    TopRight = InsideCornerOperation("Top Right", True, False, "")
    BottomRight = InsideCornerOperation("Bottom Right", True, True, "")
    BottomLeft = InsideCornerOperation("Bottom Left", False, False, "")
