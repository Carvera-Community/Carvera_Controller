"""Raise Gradle's heap before the APK is assembled.

python-for-android's SDL2 bootstrap leaves the Gradle daemon on its default
heap. Packaging matplotlib's data files then fails in :packageDebug with no
nested message, which is the worker running out of memory.
"""

from pathlib import Path

_JVMARGS = (
    "org.gradle.jvmargs=-Xmx4g -XX:MaxMetaspaceSize=512m "
    "-XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8\n"
)


def before_apk_assemble(toolchain):
    path = Path("gradle.properties")
    text = path.read_text() if path.exists() else ""
    if "org.gradle.jvmargs=" in text:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + _JVMARGS)
