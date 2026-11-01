"""Colours come from theme tokens, not literals scattered through kv and Python.

Add a token to ``carveracontroller/ui/theme.py`` and read it with
``app.theme.<token>`` (kv) or ``get_theme()`` (Python). If a literal is really
data (a user preference, a material preset, a texture-tint mask), add it to
``_ALLOWED`` with the reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / "carveracontroller"

_NUM = r"-?(?:\d+\.?\d*|\.\d+)(?:\s*/\s*255)?"
_THREE_NUMBERS = re.compile(rf"(?<![\w.\]])\s*{_NUM}\s*,\s*{_NUM}\s*,\s*{_NUM}(?![\w\[])")
_TRANSPARENT_QUAD = re.compile(r"[\[(]?\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?\s*,\s*0(?:\.0+)?\s*[\])]?")
_WHITE_QUAD = re.compile(r"[\[(]?\s*1(?:\.0+)?\s*,\s*1(?:\.0+)?\s*,\s*1(?:\.0+)?\s*,\s*1(?:\.0+)?\s*[\])]?")
_KV_COLOR_KEY = re.compile(r"^\s*([\w.]*(?:color|rgba|rgb)\w*)\s*:\s*(.+)$", re.IGNORECASE)
_PY_COLOR_ASSIGN = re.compile(r"\b[\w.]*(?:color|rgba|rgb)\w*\s*[=:]\s*(.+)$", re.IGNORECASE)
_PY_COLOR_CALL = re.compile(r"\bColor\(\s*(.+)")
_MARKUP_HEX = re.compile(r"\[color=#?[0-9a-fA-F]{6}\]")

# file (relative to carveracontroller/) -> reason, for files that are not scanned at all.
_SKIPPED_FILES = {
    "ui/theme.py": "defines the palette",
    "Controller.py": "machine state colours stay in the controller layer; the UI resolves them "
    "through ui.theme.machine_state_color",
    "addons/stock/stock_material.py": "material appearance presets (data)",
    "addons/beds/materials.py": "bed material appearance presets (data)",
}

# file -> substrings of source lines that may keep a literal, with the reason.
_ALLOWED = {
    "GcodeViewer.py": [
        ("[1.0, 0.0, 0.0] if linedata[4] == 0.0 else [0.0, 1.0, 0.0]", "rapid/feed move-type vertex colours"),
    ],
    "ui/tutorial/overlay.py": [("(0, 0, 0, 0)", "safe-area padding, not a colour")],
}


def _source_files(suffix: str):
    for path in sorted(_PKG.rglob(f"*{suffix}")):
        rel = path.relative_to(_PKG).as_posix()
        if rel in _SKIPPED_FILES or "__pycache__" in path.parts:
            continue
        yield rel, path


def _strip_comment(line: str) -> str:
    # Good enough for kv and Python here: no '#' inside colour expressions.
    return line.split("#", 1)[0]


def _is_literal(value: str, *, allow_white_mask: bool) -> bool:
    """True when ``value`` holds a colour made only of numbers."""
    value = _TRANSPARENT_QUAD.sub("", value)
    if allow_white_mask:
        value = _WHITE_QUAD.sub("", value)
    return bool(_THREE_NUMBERS.search(value))


def _allowed(rel: str, line: str) -> bool:
    return any(snippet in line for snippet, _reason in _ALLOWED.get(rel, ()))


def _kv_violations():
    for rel, path in _source_files(".kv"):
        for number, raw in enumerate(path.read_text().splitlines(), 1):
            line = _strip_comment(raw)
            match = _KV_COLOR_KEY.match(line)
            if match:
                key, value = match.groups()
                # A white `rgba` on a canvas instruction only tints a texture.
                mask_ok = key.lower() == "rgba"
                if _is_literal(value, allow_white_mask=mask_ok) and not _allowed(rel, raw):
                    yield f"{rel}:{number}: {raw.strip()}"
            if _MARKUP_HEX.search(raw) and not _allowed(rel, raw):
                yield f"{rel}:{number}: markup colour {raw.strip()}"


def _py_violations():
    for rel, path in _source_files(".py"):
        for number, raw in enumerate(path.read_text().splitlines(), 1):
            line = _strip_comment(raw)
            if not line.strip() or _allowed(rel, raw):
                continue
            call = _PY_COLOR_CALL.search(line)
            if call and _is_literal(call.group(1).split(")")[0], allow_white_mask=True):
                yield f"{rel}:{number}: {raw.strip()}"
                continue
            assign = _PY_COLOR_ASSIGN.search(line)
            if assign and _is_literal(assign.group(1), allow_white_mask=True):
                yield f"{rel}:{number}: {raw.strip()}"


def test_kv_files_use_theme_tokens():
    found = list(_kv_violations())
    assert not found, "Hard-coded colours in kv files (use app.theme.<token>):\n" + "\n".join(found)


def test_python_files_use_theme_tokens():
    found = list(_py_violations())
    assert not found, "Hard-coded colours in Python (use get_theme()):\n" + "\n".join(found)


def test_scanner_flags_literals_and_accepts_tokens():
    assert _is_literal("50/255, 50/255, 50/255, 1", allow_white_mask=False)
    assert _is_literal("(0.2, 0.5, 0.5, 0.5)", allow_white_mask=False)
    assert _is_literal("[.7,.7,.7,.9]", allow_white_mask=False)
    assert _is_literal("(80/255, 80/255, 80/255, 1) if self.selected else app.theme.row_alt", allow_white_mask=False)
    assert not _is_literal("app.theme.panel", allow_white_mask=False)
    assert not _is_literal("app.theme.bg[0], app.theme.bg[1], app.theme.bg[2], .28", allow_white_mask=False)
    assert not _is_literal("0, 0, 0, 0", allow_white_mask=False)
    assert not _is_literal("(1, 1, 1, 1) if root.thumbnail else (0, 0, 0, 0)", allow_white_mask=True)
    assert _is_literal("1, 1, 1, 1", allow_white_mask=False)


@pytest.mark.parametrize("rel", sorted(_SKIPPED_FILES))
def test_skipped_files_exist(rel):
    assert (_PKG / rel).is_file(), f"{rel} is skipped but no longer exists; drop it from _SKIPPED_FILES"
