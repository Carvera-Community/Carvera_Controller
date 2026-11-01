"""
Open SDL joysticks on the same libSDL2 instance Kivy already initialized.

Kivy never dispatches SDL_JOYDEVICEADDED, so pads plugged in after startup are
never passed to SDL_JoystickOpen. We periodically call SDL_JoystickUpdate and
open device indices whose instance id we have not opened yet. SDL does not
reuse instance ids, so an unplugged controller that is plugged back in must be
opened again, and the previous id must be dropped.

A naive ctypes CDLL("libSDL2.so") can map a second, uninitialized copy of SDL;
this module resolves the libSDL2 path linked from kivy.core.window._window_sdl2
and rejects mappings where SDL_WasInit(0) does not match Kivy's subsystems.
On macOS, Kivy's SDL is the image dyld already loaded for that module.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from ctypes import CDLL, c_char_p, c_int, c_int32, c_uint, c_uint32, c_void_p
from ctypes.util import find_library
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SDL_INIT_VIDEO = 0x00000020
SDL_INIT_JOYSTICK = 0x00000200
_KIVY_SDL_BITS = SDL_INIT_VIDEO | SDL_INIT_JOYSTICK

_sdl2_dll: Any | None = None  # CDLL, or False after permanent load failure
# instance id -> SDL_Joystick* opened by this module. SDL instance ids are not reused,
# so a controller unplugged and plugged back in is a new id at device index 0.
_opened_joysticks: dict[int, int] = {}


def _darwin_loaded_sdl2_paths() -> list[str]:
    """Filesystem paths of SDL2 already mapped into this process."""
    try:
        dyld = CDLL("/usr/lib/system/libdyld.dylib")
        dyld._dyld_image_count.restype = c_uint32
        dyld._dyld_get_image_name.argtypes = [c_uint32]
        dyld._dyld_get_image_name.restype = c_char_p
        count = int(dyld._dyld_image_count())
    except (OSError, AttributeError):
        return []
    paths: list[str] = []
    for index in range(count):
        raw = dyld._dyld_get_image_name(index)
        if not raw:
            continue
        path = os.fsdecode(raw)
        base = os.path.basename(path)
        if "SDL2_" in base:
            continue
        if base == "SDL2" or base.startswith(("libSDL2.", "libSDL2-")):
            paths.append(path)
    return paths


def _kivy_window_module_path() -> str | None:
    try:
        from kivy.core.window import _window_sdl2 as mod
    except ImportError:
        return None
    return str(Path(mod.__file__).resolve())


def _libsdl2_paths_linked_by_kivy(so_path: str) -> list[str]:
    """SDL2 paths listed for `_window_sdl2` (same mapping as Kivy's SDL_Init)."""
    try:
        if sys.platform.startswith("linux"):
            r = subprocess.run(
                ["ldd", so_path],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            blob = (r.stdout or "") + (r.stderr or "")
            if "not a dynamic executable" in blob:
                logger.warning(
                    "Gamepad SDL: Kivy window module looks statically linked; "
                    "use a build linked to shared libSDL2 for controller hot-plug",
                )
                return []
            paths: list[str] = []
            for line in blob.splitlines():
                if "libSDL2" not in line or "=>" not in line:
                    continue
                rhs = line.split("=>", 1)[1].strip().split()[0]
                if rhs and not rhs.startswith("not"):
                    paths.append(rhs)
            return paths
        if sys.platform == "win32":
            folder = os.path.dirname(so_path)
            return [
                os.path.join(folder, name)
                for name in ("SDL2.dll", "libSDL2.dll")
                if os.path.isfile(os.path.join(folder, name))
            ]
    except Exception:
        pass
    return []


def _unique_strs(paths: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _sdl2_candidate_paths() -> list[str]:
    chunks: list[str] = []
    so = _kivy_window_module_path()
    if sys.platform == "darwin":
        chunks.extend(_darwin_loaded_sdl2_paths())
    elif so:
        chunks.extend(_libsdl2_paths_linked_by_kivy(so))
    lib = find_library("SDL2")
    if lib:
        chunks.append(lib)
    if sys.platform == "win32":
        chunks.extend(("SDL2", "SDL2.dll"))
    elif sys.platform == "darwin":
        chunks.extend(("libSDL2.dylib", "SDL2"))
    else:
        chunks.extend(("libSDL2-2.0.so.0", "libSDL2.so"))
    return _unique_strs(chunks)


def _is_kivy_initialized_sdl(dll: Any) -> tuple[bool, int]:
    dll.SDL_WasInit.argtypes = [c_uint]
    dll.SDL_WasInit.restype = c_uint
    mask = int(dll.SDL_WasInit(0))
    return (mask & _KIVY_SDL_BITS) == _KIVY_SDL_BITS, mask


def _load_sdl2() -> Any | None:
    global _sdl2_dll
    if _sdl2_dll is False:
        return None
    if _sdl2_dll is not None:
        return _sdl2_dll

    rejected: list[str] = []
    for path in _sdl2_candidate_paths():
        try:
            dll = CDLL(path)
        except OSError:
            continue
        ok, mask = _is_kivy_initialized_sdl(dll)
        if not ok:
            rejected.append(f"{path!r} WasInit=0x{mask:x}")
            continue
        _sdl2_dll = dll
        return dll

    if rejected:
        logger.warning(
            "Gamepad SDL: no libSDL2 matched Kivy's instance — %s",
            "; ".join(rejected),
        )
    else:
        logger.warning("Gamepad SDL: could not load libSDL2")
    _sdl2_dll = False
    return None


def _bind_sdl_joystick_api(sdl: Any) -> None:
    sdl.SDL_WasInit.argtypes = [c_uint]
    sdl.SDL_WasInit.restype = c_uint
    sdl.SDL_JoystickUpdate.argtypes = []
    sdl.SDL_JoystickUpdate.restype = None
    sdl.SDL_NumJoysticks.argtypes = []
    sdl.SDL_NumJoysticks.restype = c_int
    sdl.SDL_JoystickGetDeviceInstanceID.argtypes = [c_int]
    sdl.SDL_JoystickGetDeviceInstanceID.restype = c_int32
    sdl.SDL_JoystickOpen.argtypes = [c_int]
    sdl.SDL_JoystickOpen.restype = c_void_p
    sdl.SDL_JoystickClose.argtypes = [c_void_p]
    sdl.SDL_JoystickClose.restype = None
    sdl.SDL_GetError.argtypes = []
    sdl.SDL_GetError.restype = c_char_p


def ensure_sdl_joysticks_open() -> set[int] | None:
    """Open joysticks that appeared since the last call and close ones that left.

    Returns the instance ids currently connected, or None if Kivy's SDL could
    not be used. Instance ids are not reused: a controller plugged back in is a
    new id, often still at device index 0.
    """
    sdl = _load_sdl2()
    if sdl is None:
        return None
    try:
        _bind_sdl_joystick_api(sdl)
        inited = sdl.SDL_WasInit(0)
        if not (inited & SDL_INIT_JOYSTICK):
            logger.warning(
                "Gamepad SDL: joystick subsystem not initialized (WasInit=0x%x)",
                inited,
            )
            return None
        sdl.SDL_JoystickUpdate()
        n = int(sdl.SDL_NumJoysticks())
        present: dict[int, int] = {}
        for index in range(n):
            instance_id = int(sdl.SDL_JoystickGetDeviceInstanceID(index))
            if instance_id < 0:
                continue
            handle = _opened_joysticks.get(instance_id)
            if handle is None:
                handle = sdl.SDL_JoystickOpen(index)
                if not handle:
                    err = sdl.SDL_GetError()
                    detail = err.decode("utf-8", "replace") if err else ""
                    logger.warning(
                        "Gamepad SDL: SDL_JoystickOpen(%d) failed: %r",
                        index,
                        detail,
                    )
                    continue
                handle = int(handle)
                _opened_joysticks[instance_id] = handle
                logger.debug("Gamepad SDL: opened joystick index %d instance %d", index, instance_id)
            present[instance_id] = handle
        for instance_id, handle in list(_opened_joysticks.items()):
            if instance_id not in present:
                sdl.SDL_JoystickClose(handle)
                del _opened_joysticks[instance_id]
                logger.debug("Gamepad SDL: closed joystick instance %d", instance_id)
        return set(present)
    except Exception:
        logger.warning("Gamepad SDL: error opening joysticks", exc_info=True)
        return None
