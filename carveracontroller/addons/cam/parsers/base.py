"""Base class for CAM G-code header parsers."""

from abc import ABC, abstractmethod

from carveracontroller.addons.cam.metadata import CamMetadata

# Characters that make a line "safe" to skip over while looking for a CAM
# header (comment, blank, program-marker or variable-assignment lines).
# Mirrors the characters CNC.parseLine() itself treats as non-motion lines.
HEADER_SAFE_PREFIXES = ("%", "(", "#", ";")

# Hard cap on how many lines a header scan will ever look at, in case a file
# has an unusually long run of leading comments with no actual G-code.
MAX_HEADER_LINES = 5000


class CamHeaderParser(ABC):
    """Extracts CAM metadata from the raw lines of a G-code file.

    Implementations should be conservative: if the file does not look like
    it was produced by the CAM/post processor they support, `parse()` should
    return an empty dict rather than guessing.
    """

    name = "base"

    @abstractmethod
    def parse(self, lines):
        """Parse (an iterable of) raw G-code file lines.

        Returns a dict mapping tool number (int) -> ToolDefinition. If a
        tool number appears in multiple comments, only the first occurrence
        found in the file should be kept.
        """
        raise NotImplementedError

    def parse_metadata(self, lines, unit_scale=1.0) -> CamMetadata:
        """Parse tools and stock from the same header scan.

        Default wraps :meth:`parse` with ``stock=None``. Override when a
        post processor also emits stock comments so both are read in one pass.

        ``unit_scale`` converts document-unit stock sizes/offsets to millimetres
        (1.0 for mm files, 25.4 for inch files). Tools are left in document units.
        """
        return CamMetadata(parser_name=self.name, tool_table=self.parse(lines) or {}, stock=None)

    @staticmethod
    def iter_header_lines(lines, max_lines=MAX_HEADER_LINES):
        """Lazily yield the leading blank/comment-only lines of a file.

        CAM post processors write metadata as a block of comments at the
        very top of the file, before any real G-code. So instead of scanning
        the whole (potentially huge) file, parsers that rely on this stop
        pulling from `lines` as soon as the first "real" line is seen (or
        after `max_lines`), without ever materialising a separate list.
        """
        for count, line in enumerate(lines):
            if count >= max_lines:
                return
            stripped = line.strip()
            if stripped and stripped[0] not in HEADER_SAFE_PREFIXES:
                return
            yield line
