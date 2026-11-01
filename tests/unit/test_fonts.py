"""Theme fonts: resolving a name or path to a Kivy ``font_name``."""

import ctypes
import os
import struct
import subprocess
import sys
from types import SimpleNamespace

import pytest

from carveracontroller.ui import themes
from carveracontroller.ui.fonts import fonts
from carveracontroller.ui.fonts.fonts import ARIALUNI, arialuni_path, resolve_font, resolve_theme_fonts
from carveracontroller.ui.theme import Theme
from carveracontroller.ui.themes import BASE_THEME

_REAL_FONT_SCAN = {
    "test_scan_follows_the_platform",
    "test_android_environment_uses_the_android_scanner",
    "test_ios_environment_uses_the_ios_scanner",
}


@pytest.fixture(autouse=True)
def no_system_fonts(monkeypatch, request):
    """Keep the tests independent of the fonts installed on the machine."""
    fonts._index_cache = None
    # Those tests check which scanner each system uses, so they keep the real one.
    if request.node.originalname not in _REAL_FONT_SCAN:
        monkeypatch.setattr(fonts, "_load_font_index", lambda: {})
    yield
    fonts._index_cache = None


def test_bundled_font_file_exists():
    assert os.path.isfile(arialuni_path())


def test_empty_and_arialuni_specs_give_arialuni():
    for spec in (None, "", "   ", 5, "ARIALUNI", "arialuni"):
        assert resolve_font(spec) == ARIALUNI


def test_existing_font_path_is_used_as_is():
    assert resolve_font(arialuni_path()) == arialuni_path()


def test_missing_path_or_wrong_extension_falls_back(tmp_path, caplog):
    text_file = tmp_path / "notes.txt"
    text_file.write_text("x")
    for spec in (str(tmp_path / "missing.ttf"), str(text_file), "fonts/missing.ttf", "missing.otf"):
        assert resolve_font(spec) == ARIALUNI
    assert "not found" in caplog.text


def _face_path(index, family, weight="Regular", italic=False):
    for face in index[family]:
        if face.weight == weight and face.italic == italic:
            return face.path
    raise AssertionError((family, weight, italic))


def test_family_name_resolves_from_the_index(monkeypatch, tmp_path):
    regular = tmp_path / "Regular.ttf"
    bold = tmp_path / "Bold.ttf"
    italic = tmp_path / "Italic.ttf"
    for path in (regular, bold, italic):
        path.write_bytes(b"")
    faces = (
        fonts.FontFace("DejaVu Sans", "Regular", False, str(regular), 400),
        fonts.FontFace("DejaVu Sans", "Bold", False, str(bold), 700),
        fonts.FontFace("DejaVu Sans", "Regular", True, str(italic), 400),
    )
    monkeypatch.setattr(fonts, "_load_font_index", lambda: {"DejaVu Sans": faces})
    fonts._index_cache = None

    assert resolve_font("DejaVu Sans") == "DejaVu Sans [Regular Roman]"
    assert resolve_font("dejavu sans") == "DejaVu Sans [Regular Roman]"
    assert resolve_font({"family": "DejaVu Sans", "weight": "Bold", "style": "Roman"}) == "DejaVu Sans [Bold Roman]"
    assert (
        resolve_font({"family": "DejaVu Sans", "weight": "Regular", "style": "Italic"})
        == "DejaVu Sans [Regular Italic]"
    )
    assert resolve_font("Nobody Has This") == ARIALUNI

    from kivy.core.text import LabelBase

    regular_slots = LabelBase._fonts["DejaVu Sans [Regular Roman]"]
    bold_slots = LabelBase._fonts["DejaVu Sans [Bold Roman]"]
    italic_slots = LabelBase._fonts["DejaVu Sans [Regular Italic]"]
    assert regular_slots == (str(regular), str(italic), str(bold), str(italic))
    assert bold_slots[0] == str(bold)
    assert bold_slots[2] == str(bold)
    assert italic_slots[0] == str(italic)
    assert italic_slots[2] == str(bold)


def test_roles_default_to_arialuni_and_other_roles_follow_default():
    arialuni = {"default": ARIALUNI, "top_bar": ARIALUNI, "jog_pad": ARIALUNI, "code_list": ARIALUNI}
    assert resolve_theme_fonts({}) == arialuni
    assert resolve_theme_fonts(None) == arialuni
    path = arialuni_path()
    followed = {"default": path, "top_bar": path, "jog_pad": path, "code_list": path}
    assert resolve_theme_fonts({"default": path}) == followed
    assert resolve_theme_fonts({"top_bar": path}) == {**arialuni, "top_bar": path}
    assert resolve_theme_fonts({"jog_pad": path}) == {**arialuni, "jog_pad": path}
    assert resolve_theme_fonts({"code_list": path}) == {**arialuni, "code_list": path}


def test_theme_font_properties_start_on_arialuni():
    theme = Theme()
    assert theme.font_default == ARIALUNI
    assert theme.font_top_bar == ARIALUNI
    assert theme.font_jog_pad == ARIALUNI
    assert theme.font_code_list == ARIALUNI


@pytest.fixture
def font_themes(tmp_path, monkeypatch):
    monkeypatch.setattr(themes, "THEMES_DIR", tmp_path)
    themes._load_cached.cache_clear()
    source = themes.Path(themes.__file__).parent / "bundled" / f"{BASE_THEME}.json"
    (tmp_path / f"{BASE_THEME}.json").write_text(source.read_text())
    yield tmp_path
    themes._load_cached.cache_clear()


def _write(directory, name, data):
    import json

    (directory / f"{name}.json").write_text(json.dumps(data))


def test_apply_palette_sets_font_roles_independently_and_resets(font_themes):
    path = arialuni_path()
    _write(font_themes, "bar_only", {"extends": BASE_THEME, "fonts": {"top_bar": path}})
    _write(font_themes, "both", {"extends": BASE_THEME, "fonts": {"default": path}})
    theme = Theme()

    theme.apply_palette("bar_only")
    assert (theme.font_default, theme.font_top_bar, theme.font_jog_pad, theme.font_code_list) == (
        ARIALUNI,
        path,
        ARIALUNI,
        ARIALUNI,
    )

    theme.apply_palette("both")
    assert (theme.font_default, theme.font_top_bar, theme.font_jog_pad, theme.font_code_list) == (
        path,
        path,
        path,
        path,
    )

    theme.apply_palette(BASE_THEME)
    assert (theme.font_default, theme.font_top_bar, theme.font_jog_pad, theme.font_code_list) == (
        ARIALUNI,
        ARIALUNI,
        ARIALUNI,
        ARIALUNI,
    )


def test_color_apply_leaves_fonts_alone(font_themes):
    path = arialuni_path()
    _write(font_themes, "styled", {"extends": BASE_THEME, "fonts": {"default": path}})
    theme = Theme("styled")
    assert theme.font_default == path
    theme.apply({"accent": (255, 0, 0, 255)})
    assert theme.font_default == path


def test_theme_constructed_with_a_font_palette(font_themes):
    path = arialuni_path()
    _write(font_themes, "styled", {"extends": BASE_THEME, "fonts": {"top_bar": path}})
    theme = Theme("styled")
    assert (theme.font_default, theme.font_top_bar, theme.font_jog_pad, theme.font_code_list) == (
        ARIALUNI,
        path,
        ARIALUNI,
        ARIALUNI,
    )


def test_available_families_puts_the_bundled_alias_first(monkeypatch):
    monkeypatch.setattr(
        fonts, "_load_font_index", lambda: {"aaa": "/a.ttf", "DejaVu Sans": "/b.ttf", "ARIALUNI": "/c.ttf"}
    )
    fonts._index_cache = None
    assert fonts.available_families() == ["ARIALUNI", "aaa", "DejaVu Sans"]


def test_finished_scan_is_cached_and_a_timeout_is_retried(monkeypatch):
    calls = {"n": 0}

    def load():
        calls["n"] += 1
        return None if calls["n"] < 3 else {"DejaVu Sans": "/fonts/DejaVuSans.ttf"}

    monkeypatch.setattr(fonts, "_load_font_index", load)
    fonts._index_cache = None
    assert fonts.font_index() == {}
    assert fonts.font_index() == {}
    assert calls["n"] == 2
    assert fonts.font_index() == {"DejaVu Sans": "/fonts/DejaVuSans.ttf"}
    assert fonts.font_index() == {"DejaVu Sans": "/fonts/DejaVuSans.ttf"}
    assert calls["n"] == 3


def test_missing_fc_list_is_empty_and_a_timeout_is_not(monkeypatch):
    monkeypatch.setattr(fonts.shutil, "which", lambda _name: None)
    assert fonts._fontconfig_index() == {}

    monkeypatch.setattr(fonts.shutil, "which", lambda _name: "/usr/bin/fc-list")

    def timed_out(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="fc-list", timeout=15)

    monkeypatch.setattr(fonts.subprocess, "run", timed_out)
    assert fonts._fontconfig_index() is None

    def undecodable(*_args, **_kwargs):
        raise UnicodeDecodeError("ascii", b"\xff", 0, 1, "ordinal not in range(128)")

    monkeypatch.setattr(fonts.subprocess, "run", undecodable)
    assert fonts._fontconfig_index() == {}


def test_fc_list_keeps_rows_when_a_name_is_not_utf8(tmp_path, monkeypatch):
    face = tmp_path / "Sans.ttf"
    face.write_bytes(b"")
    payload = b"Caf\xff|Regular|" + os.fsencode(face) + b"|0\n"
    payload += f"DejaVu Sans|Regular|{face}|0\n".encode()

    def run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["fc-list"], returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr(fonts.shutil, "which", lambda _name: "/usr/bin/fc-list")
    monkeypatch.setattr(fonts.subprocess, "run", run)
    index = fonts._fontconfig_index()
    assert "DejaVu Sans" in index
    assert any(name.startswith("Caf") for name in index)


def test_fc_list_keeps_one_regular_file_per_family(tmp_path):
    regular = tmp_path / "Sans.ttf"
    bold = tmp_path / "Sans-Bold.ttf"
    book = tmp_path / "Sans-Book.otf"
    postscript = tmp_path / "Courier.pfb"
    for path in (regular, bold, book, postscript):
        path.write_bytes(b"")
    stdout = "\n".join(
        [
            f"Sans|Book|{book}|0",
            f"Sans|Bold|{bold}|0",
            f"Sans|Regular|{regular}|0",
            f"Courier|Regular|{postscript}|0",
            f"Math|Regular|{regular}|2",
            "not a row",
        ]
    )
    records = fonts._parse_fc_list(stdout)
    assert ("Math", "Regular", str(regular), 2) in records
    index = fonts._index_from_records(records, trust_face=True)
    assert _face_path(index, "Sans") == str(regular)
    assert _face_path(index, "Sans", "Bold") == str(bold)
    assert "Courier" not in index
    assert "Math" not in index


def test_registry_names_keep_the_regular_face_and_let_a_later_one_override(tmp_path):
    for name in ("times.ttf", "timesbd.ttf", "arial.ttf", "arial-user.ttf", "cour.ttf", "cour-user.ttf"):
        (tmp_path / name).write_bytes(b"")
    entries = [
        ("Times New Roman (TrueType)", "times.ttf"),
        ("Times New Roman Bold (TrueType)", "timesbd.ttf"),
        ("Arial Bold (TrueType)", "arialbd.ttf"),
        ("Arial (TrueType)", "arial.ttf"),
        ("Arial Regular (TrueType)", str(tmp_path / "arial-user.ttf")),
        ("Courier New (TrueType)", "cour.ttf"),
        ("Courier New (TrueType)", str(tmp_path / "cour-user.ttf")),
        ("Consolas (TrueType)", "consola.ttf"),
    ]
    index = fonts._index_from_records(fonts._records_from_registry(entries, str(tmp_path)))
    assert _face_path(index, "Times New Roman") == str(tmp_path / "times.ttf")
    assert _face_path(index, "Times New Roman", "Bold") == str(tmp_path / "timesbd.ttf")
    assert "Times New" not in index
    assert "Times New Roman Bold" not in index
    assert _face_path(index, "Arial") == str(tmp_path / "arial-user.ttf")
    assert _face_path(index, "Courier New") == str(tmp_path / "cour-user.ttf")
    assert "Consolas" not in index


def test_collection_keeps_only_the_family_of_face_zero(tmp_path, monkeypatch):
    collection = tmp_path / "cambria.ttc"
    collection.write_bytes(b"ttc")
    monkeypatch.setattr(fonts, "_collection_family", lambda _path: "Cambria")
    records = [
        ("Cambria", "", str(collection), 0),
        ("Cambria Math", "", str(collection), 0),
    ]
    index = fonts._index_from_records(records)
    assert _face_path(index, "Cambria") == str(collection)
    assert "Cambria Math" not in index


@pytest.mark.parametrize(
    ("platform_name", "loader"),
    [("win32", "_windows_font_index"), ("darwin", "_macos_font_index"), ("linux", "_fontconfig_index")],
)
def test_scan_follows_the_platform(monkeypatch, platform_name, loader):
    for key in ("ANDROID_ARGUMENT", "ANDROID_PRIVATE", "ANDROID_APP_PATH", "KIVY_BUILD"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(fonts.sys, "platform", platform_name)
    monkeypatch.setattr(fonts, loader, lambda: {"Named": "named.ttf"})
    assert fonts._load_font_index() == {"Named": "named.ttf"}


def test_android_environment_uses_the_android_scanner(monkeypatch):
    import carveracontroller.main  # noqa: F401  # load before the env var is set

    monkeypatch.setattr(fonts.sys, "platform", "linux")
    monkeypatch.setenv("ANDROID_ARGUMENT", "1")
    monkeypatch.setattr(fonts, "_android_font_index", lambda: {"Roboto": "roboto.ttf"})
    monkeypatch.setattr(fonts, "_fontconfig_index", lambda: {"DejaVu Sans": "dejavu.ttf"})
    assert fonts._load_font_index() == {"Roboto": "roboto.ttf"}


def test_ios_environment_uses_the_ios_scanner(monkeypatch):
    import carveracontroller.main  # noqa: F401  # load before the env var is set

    monkeypatch.setattr(fonts.sys, "platform", "ios")
    monkeypatch.delenv("KIVY_BUILD", raising=False)
    monkeypatch.setattr(fonts, "_ios_font_index", lambda: {"Helvetica": "helvetica.ttc"})
    monkeypatch.setattr(fonts, "_fontconfig_index", lambda: {"DejaVu Sans": "dejavu.ttf"})
    assert fonts._load_font_index() == {"Helvetica": "helvetica.ttc"}

    monkeypatch.setattr(fonts.sys, "platform", "linux")
    monkeypatch.setenv("KIVY_BUILD", "ios")
    assert fonts._load_font_index() == {"Helvetica": "helvetica.ttc"}


def test_italic_only_style_is_regular_italic():
    assert fonts._classify_style("Italic") == ("Regular", True, 0)
    assert fonts._classify_style("Oblique") == ("Regular", True, 0)
    assert fonts._classify_style("Condensed Italic") == ("Regular", True, 1)
    assert fonts._classify_style("Condensed") is None


def _sfnt_font(names: tuple[tuple[int, str], ...], origin: int = 0) -> bytes:
    """Minimal TrueType whose name table holds Windows English ``(name_id, text)`` records."""
    strings = b""
    records = b""
    for name_id, text in names:
        encoded = text.encode("utf-16-be")
        records += struct.pack(">HHHHHH", 3, 1, 0x0409, name_id, len(encoded), len(strings))
        strings += encoded
    string_offset = 6 + len(names) * 12
    table = struct.pack(">HHH", 0, len(names), string_offset) + records + strings
    directory = b"name" + struct.pack(">III", 0, origin + 28, len(table))
    header = b"\x00\x01\x00\x00" + struct.pack(">HHHH", 1, 16, 0, 0)
    return header + directory + table


def _sfnt_collection(names: tuple[tuple[int, str], ...]) -> bytes:
    return b"ttcf" + struct.pack(">III", 0x00010000, 1, 16) + _sfnt_font(names, origin=16)


def test_sfnt_family_prefers_the_typographic_name_and_reads_a_collection(tmp_path):
    legacy = tmp_path / "Legacy-Bold.ttf"
    legacy.write_bytes(_sfnt_font(((1, "Roboto Bold"),)))
    assert fonts._sfnt_family(str(legacy)) == "Roboto"

    named = tmp_path / "Named.ttf"
    named.write_bytes(_sfnt_font(((1, "Roboto Bold"), (16, "Roboto"))))
    assert fonts._sfnt_family(str(named)) == "Roboto"

    collection = tmp_path / "NotoSansCJK-Regular.ttc"
    collection.write_bytes(_sfnt_collection(((16, "Noto Sans CJK JP"),)))
    assert fonts._sfnt_family(str(collection)) == "Noto Sans CJK JP"
    assert fonts._sfnt_family(str(tmp_path / "missing.ttf")) is None


@pytest.mark.parametrize(
    ("filename", "family"),
    [
        ("Roboto-Regular.ttf", "Roboto"),
        ("Roboto-BoldItalic.ttf", "Roboto"),
        ("RobotoSemiBold.ttf", "Roboto"),
        ("NotoSerif-Regular.ttf", "Noto Serif"),
        ("NotoSansCJK-Regular.ttc", "Noto Sans CJK"),
        ("DroidSansMono.ttf", "Droid Sans Mono"),
        ("GoogleSans-Medium.ttf", "Google Sans"),
        ("ComingSoon.ttf", "Coming Soon"),
        ("RobotoCondensed-Regular.ttf", "Roboto Condensed"),
        ("Facebook.ttf", "Facebook"),
    ],
)
def test_family_from_filename_drops_the_style_and_keeps_the_rest(filename, family):
    assert fonts._family_from_filename(filename) == family


def test_android_font_config_lists_system_families(tmp_path):
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    files = {
        "Roboto-Regular.ttf": ((16, "Roboto"),),
        "Roboto-Bold.ttf": ((16, "Roboto"),),
        "Roboto-Italic.ttf": ((16, "Roboto"),),
        "RobotoCondensed-Regular.ttf": ((16, "Roboto Condensed"),),
        "NotoSerif-Regular.ttf": ((1, "Noto Serif"),),
        "NotoColorEmoji.ttf": ((16, "Noto Color Emoji"),),
        "NotoSansCJK-Regular.ttc": ((16, "Noto Sans CJK JP"),),
        "RobotoFlex.ttf": ((16, "Roboto Flex"),),
        "GoogleSans-Regular.ttf": ((16, "Google Sans"),),
    }
    for name, records in files.items():
        blob = _sfnt_collection(records) if name.endswith(".ttc") else _sfnt_font(records)
        (font_dir / name).write_bytes(blob)
    outside = tmp_path / "DancingScript-Regular.ttf"
    outside.write_bytes(_sfnt_font(((16, "Dancing Script"),)))

    config = tmp_path / "fonts.xml"
    config.write_text(
        f"""<?xml version="1.0"?>
        <familyset version="23">
            <family name="sans-serif">
                <font weight="400" style="normal">Roboto-Regular.ttf</font>
                <font weight="400" style="italic">Roboto-Italic.ttf</font>
                <font weight="700" style="normal">Roboto-Bold.ttf</font>
                <font weight="400" style="normal" index="2">NotoSansCJK-Regular.ttc</font>
            </family>
            <family name="sans-serif-condensed">
                <font weight="400" style="normal">RobotoCondensed-Regular.ttf</font>
            </family>
            <family lang="und-Arab">
                <font weight="400" style="normal">NotoSerif-Regular.ttf</font>
            </family>
            <family>
                <font weight="400" style="normal">NotoColorEmoji.ttf</font>
            </family>
            <family lang="ja">
                <font weight="400" style="normal" index="0">NotoSansCJK-Regular.ttc</font>
            </family>
            <family name="sans-serif-flex">
                <font weight="100" style="normal">RobotoFlex.ttf
                    <axis tag="wght" stylevalue="100.0"/>
                </font>
                <font weight="400" style="normal">RobotoFlex.ttf</font>
                <font weight="700" style="normal">RobotoFlex.ttf</font>
            </family>
            <family name="casual">
                <font weight="400" style="normal">{outside}</font>
            </family>
            <alias name="sans-serif-medium" to="sans-serif" weight="500"/>
            <family name="missing">
                <font weight="400" style="normal">NotThere.ttf</font>
            </family>
        </familyset>
        """
    )
    overlay = tmp_path / "fonts_customization.xml"
    overlay.write_text(
        """
        <fonts-modification version="1">
            <family customizationType="new-named-family" name="google-sans">
                <font weight="400" style="normal">GoogleSans-Regular.ttf</font>
            </family>
        </fonts-modification>
        """
    )
    index = fonts._android_font_index((str(config), str(overlay)), (str(font_dir),))

    assert set(index) == {
        "Roboto",
        "Roboto Condensed",
        "Noto Serif",
        "Noto Sans CJK JP",
        "Roboto Flex",
        "Dancing Script",
        "Google Sans",
    }
    assert _face_path(index, "Roboto") == str(font_dir / "Roboto-Regular.ttf")
    assert _face_path(index, "Roboto", "Bold") == str(font_dir / "Roboto-Bold.ttf")
    assert _face_path(index, "Roboto", italic=True) == str(font_dir / "Roboto-Italic.ttf")
    assert fonts.available_weights("Roboto", index) == ["Regular", "Bold"]
    assert fonts.available_styles("Roboto", "Regular", index) == ["Roman", "Italic"]
    assert fonts.available_weights("Roboto Flex", index) == ["Regular"]
    assert _face_path(index, "Dancing Script") == str(outside)
    assert _face_path(index, "Google Sans") == str(font_dir / "GoogleSans-Regular.ttf")


def test_android_without_a_config_reads_the_font_directory(tmp_path):
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    (font_dir / "Roboto-Regular.ttf").write_bytes(_sfnt_font(((16, "Roboto"),)))
    (font_dir / "Roboto-BoldItalic.ttf").write_bytes(_sfnt_font(((16, "Roboto"),)))
    (font_dir / "NotoColorEmoji.ttf").write_bytes(_sfnt_font(((16, "Noto Color Emoji"),)))
    (font_dir / "notes.txt").write_text("nope")
    broken = tmp_path / "broken.xml"
    broken.write_text("<fonts")

    index = fonts._android_font_index((str(broken), str(tmp_path / "missing.xml")), (str(font_dir),))
    assert set(index) == {"Roboto"}
    assert _face_path(index, "Roboto") == str(font_dir / "Roboto-Regular.ttf")
    assert _face_path(index, "Roboto", "Bold", italic=True) == str(font_dir / "Roboto-BoldItalic.ttf")


def test_android_legacy_fileset_assigns_the_four_faces(tmp_path):
    font_dir = tmp_path / "fonts"
    font_dir.mkdir()
    for name in ("Regular.ttf", "Bold.ttf", "Italic.ttf", "BoldItalic.ttf"):
        (font_dir / name).write_bytes(_sfnt_font(((16, "Roboto"),)))
    config = tmp_path / "system_fonts.xml"
    config.write_text(
        """
        <familyset>
            <family>
                <nameset><name>sans-serif</name></nameset>
                <fileset>
                    <file>Regular.ttf</file>
                    <file>Bold.ttf</file>
                    <file>Italic.ttf</file>
                    <file>BoldItalic.ttf</file>
                </fileset>
            </family>
        </familyset>
        """
    )
    index = fonts._android_font_index((str(config),), (str(font_dir),))
    assert _face_path(index, "Roboto") == str(font_dir / "Regular.ttf")
    assert _face_path(index, "Roboto", "Bold") == str(font_dir / "Bold.ttf")
    assert _face_path(index, "Roboto", italic=True) == str(font_dir / "Italic.ttf")
    assert _face_path(index, "Roboto", "Bold", italic=True) == str(font_dir / "BoldItalic.ttf")


def test_android_scan_warns_when_no_fonts_can_be_read(tmp_path, caplog):
    index = fonts._android_font_index((str(tmp_path / "missing.xml"),), (str(tmp_path),))
    assert index == {}
    assert "ARIALUNI" in caplog.text


def test_ios_keeps_the_core_text_list(monkeypatch, tmp_path):
    font_dir = tmp_path / "Fonts"
    font_dir.mkdir()
    (font_dir / "Helvetica.ttc").write_bytes(_sfnt_font(((16, "Helvetica"),)))
    monkeypatch.setattr(fonts, "_macos_font_index", lambda: {"Helvetica Neue": "neue.ttc"})

    assert fonts._ios_font_index((str(font_dir),)) == {"Helvetica Neue": "neue.ttc"}


def test_ios_without_core_text_reads_the_font_directory(monkeypatch, tmp_path):
    font_dir = tmp_path / "Core"
    font_dir.mkdir()
    (font_dir / "Helvetica.ttc").write_bytes(_sfnt_font(((16, "Helvetica"),)))
    (font_dir / "Helvetica-Bold.ttf").write_bytes(_sfnt_font(((16, "Helvetica"),)))
    (font_dir / "AppleColorEmoji.ttc").write_bytes(_sfnt_font(((16, "Apple Color Emoji"),)))
    monkeypatch.setattr(fonts, "_macos_font_index", lambda: {})

    index = fonts._ios_font_index((str(font_dir),))
    assert set(index) == {"Helvetica"}
    assert _face_path(index, "Helvetica") == str(font_dir / "Helvetica.ttc")
    assert _face_path(index, "Helvetica", "Bold") == str(font_dir / "Helvetica-Bold.ttf")


class _CoreFoundationCall:
    def __init__(self, result):
        self.result = result
        self.argtypes = None
        self.restype = None
        self.calls = []

    def __call__(self, *args):
        self.calls.append((self.argtypes, args))
        return self.result


def _core_foundation(**results):
    names = (
        "CFGetTypeID",
        "CFStringGetTypeID",
        "CFURLGetTypeID",
        "CFStringCreateWithCString",
        "CFStringGetLength",
        "CFStringGetCString",
        "CFRelease",
        "CFArrayGetCount",
        "CFArrayGetValueAtIndex",
        "CFURLGetFileSystemRepresentation",
    )
    return SimpleNamespace(**{name: _CoreFoundationCall(results.get(name, 0)) for name in names})


def test_cf_string_read_uses_a_pointer_argument_and_skips_other_types():
    """A 32-bit CFStringGetLength argument aborts macOS with NSInvalidArgumentException."""
    wide = 0x1_0000_0001_ABAD_03F0
    string = _core_foundation(CFGetTypeID=7, CFStringGetTypeID=7, CFStringGetLength=0)
    assert fonts._py_string(string, wide) == ""
    assert string.CFStringGetLength.calls[0][0][0] is ctypes.c_void_p
    assert string.CFStringGetLength.calls[0][1] == (wide,)

    other = _core_foundation(CFGetTypeID=1, CFStringGetTypeID=7, CFStringGetLength=4)
    assert fonts._py_string(other, wide) == ""
    assert other.CFStringGetLength.calls == []


def test_cf_path_skips_a_value_that_is_not_a_url():
    wide = 0x1_0000_0001_ABAD_03F0
    other = _core_foundation(CFGetTypeID=1, CFURLGetTypeID=9)
    assert fonts._cf_path(other, wide) == ""
    assert other.CFURLGetFileSystemRepresentation.calls == []


@pytest.mark.skipif(sys.platform != "darwin", reason="Core Text font scan is macOS only")
def test_macos_font_scan_returns_file_backed_faces():
    records = fonts._macos_font_records()
    assert records
    families = {family for family, _style, _path, _index in records}
    assert "Helvetica" in families or "Arial" in families
    assert any(os.path.isfile(path) for _family, _style, path, _index in records)


def test_ios_scan_warns_when_no_fonts_can_be_read(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(fonts, "_macos_font_index", lambda: {})
    index = fonts._ios_font_index((str(tmp_path),))
    assert index == {}
    assert "ARIALUNI" in caplog.text


def test_frozen_bundle_uses_meipass_or_the_executable_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(fonts.sys, "frozen", True, raising=False)
    monkeypatch.setattr(fonts.sys, "_MEIPASS", str(tmp_path), raising=False)
    bundled = os.path.abspath(tmp_path / "assets" / "fonts" / "ARIALUNI.ttf")
    assert fonts.arialuni_path() == bundled

    monkeypatch.delattr(fonts.sys, "_MEIPASS")
    monkeypatch.setattr(fonts.sys, "executable", str(tmp_path / "Carvera"))
    assert fonts.arialuni_path() == bundled


def test_register_arialuni_reports_a_missing_file(monkeypatch, tmp_path):
    missing = tmp_path / "ARIALUNI.ttf"
    monkeypatch.setattr(fonts, "arialuni_path", lambda: str(missing))
    with pytest.raises(FileNotFoundError, match="ARIALUNI"):
        fonts.register_arialuni()
