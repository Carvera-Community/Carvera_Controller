from enum import Enum
from carveracontroller.addons.probing.operations.InsideCorner.InsideCornerOperation import InsideCornerOperation

class InsideCornerOperationType(Enum):
    TopLeft = InsideCornerOperation("Inside Corner - Top Left", False, True, "")
    TopRight = InsideCornerOperation("Inside Corner - Top Right", True, True, "")
    BottomRight = InsideCornerOperation("Inside Corner - Bottom Right", True, False, "")
    BottomLeft = InsideCornerOperation("Inside Corner - Bottom Left", False, False, "")