"""Theme fonts: resolving a name or path to a Kivy ``font_name``."""

import os
import subprocess

import pytest

from carveracontroller.ui import themes
from carveracontroller.ui.fonts import fonts
from carveracontroller.ui.fonts.fonts import ARIALUNI, arialuni_path, resolve_font, resolve_theme_fonts
from carveracontroller.ui.theme import Theme
from carveracontroller.ui.themes import BASE_THEME


@pytest.fixture(autouse=True)
def no_system_fonts(monkeypatch, request):
    """Keep the tests independent of the fonts installed on the machine."""
    fonts._index_cache = None
    # That test checks which scanner each system uses, so it keeps the real one.
    if request.node.originalname != "test_scan_follows_the_platform":
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
    assert resolve_font({"family": "DejaVu Sans", "weight": "Regular", "style": "Italic"}) == "DejaVu Sans [Regular Italic]"
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
    monkeypatch.setattr(fonts.sys, "platform", platform_name)
    monkeypatch.setattr(fonts, loader, lambda: {"Named": "named.ttf"})
    assert fonts._load_font_index() == {"Named": "named.ttf"}


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
