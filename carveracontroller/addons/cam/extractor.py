"""Registry of CAM header parsers and the extraction entry point."""

import logging

from carveracontroller.addons.cam.metadata import CamMetadata
from carveracontroller.addons.cam.parsers.freecad_makera import FreeCADMakeraParser
from carveracontroller.addons.cam.parsers.fusion360_makera import Fusion360MakeraParser
from carveracontroller.addons.cam.parsers.makera_studio import MakeraStudioParser

logger = logging.getLogger(__name__)

# Ordered list of parsers to try when extracting CAM metadata from a loaded
# G-code file. Add new CAM/post-processor parsers here.
CAM_PARSERS = [
    MakeraStudioParser(),
    FreeCADMakeraParser(),
    Fusion360MakeraParser(),
]


def extract_cam_metadata(lines, unit_scale=1.0) -> CamMetadata:
    """Try each registered parser and return the first non-empty result.

    `lines` is passed as-is to each parser; well-behaved parsers bail out
    early (e.g. via `CamHeaderParser.iter_header_lines`) instead of scanning
    the whole file, so this stays cheap even for very large files.

    ``unit_scale`` converts document-unit stock sizes to millimetres (pass
    ``unit_scale_to_mm``). Tool diameters stay in document units.

    A result is non-empty when it has a tool table and/or stock. If no parser
    recognises the file, an empty :class:`CamMetadata` is returned.
    """
    for parser in CAM_PARSERS:
        try:
            metadata = parser.parse_metadata(lines, unit_scale=unit_scale)
        except Exception:
            logger.exception(f"CAM parser '{parser.name}' raised an exception, skipping it")
            metadata = CamMetadata.empty()
        if metadata.tool_table or metadata.stock:
            if metadata.tool_table:
                tool_numbers = ", ".join(f"T{number}" for number in sorted(metadata.tool_table))
                logger.info(f"Tool table extracted using parser '{parser.name}': {tool_numbers}")
            return metadata

    logger.debug("No CAM header detected in loaded file (no parser recognised it)")
    return CamMetadata.empty()
