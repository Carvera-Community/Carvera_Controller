"""Gradle heap hook used by the Android package step."""

import importlib.util
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[2] / "assets" / "packaging" / "android" / "gradle_heap_hook.py"
_spec = importlib.util.spec_from_file_location("gradle_heap_hook", _HOOK)
assert _spec is not None and _spec.loader is not None
gradle_heap_hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gradle_heap_hook)


def test_before_apk_assemble_sets_gradle_heap_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    properties = tmp_path / "gradle.properties"
    properties.write_text("android.useAndroidX=true")

    gradle_heap_hook.before_apk_assemble(None)
    gradle_heap_hook.before_apk_assemble(None)

    text = properties.read_text()
    assert text.startswith("android.useAndroidX=true\n")
    assert text.count("org.gradle.jvmargs=-Xmx4g") == 1
