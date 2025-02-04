from enum import Enum
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperation import InsideCornerOperation

class InsideCornerOperationType(Enum):
    TopLeft = InsideCornerOperation("Inside Corner - Top Left", False, False, "")
    TopRight = InsideCornerOperation("Inside Corner - Top Right", True, False, "")
    BottomRight = InsideCornerOperation("Inside Corner - Bottom Right", True, True, "")
    BottomLeft = InsideCornerOperation("Inside Corner - Bottom Left", False, False, "")
