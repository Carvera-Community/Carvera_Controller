"""CAM post-processor header parsing (tool tables and stock comments)."""

from carveracontroller.addons.cam.extractor import extract_cam_metadata
from carveracontroller.addons.cam.metadata import CamMetadata, CamStock

__all__ = [
    "CamMetadata",
    "CamStock",
    "extract_cam_metadata",
]
