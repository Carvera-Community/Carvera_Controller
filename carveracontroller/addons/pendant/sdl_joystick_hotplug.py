"""
Open SDL joysticks on the same libSDL2 instance Kivy already initialized.

Kivy never dispatches SDL_JOYDEVICEADDED, so pads plugged in after startup are
never passed to SDL_JoystickOpen. We periodically call SDL_JoystickUpdate and
open only newly appeared device indices (repeat SDL_JoystickOpen bumps ref_count
in SDL2, so we must not reopen already-open slots each tick).

A naive ctypes CDLL("libSDL2.so") can map a second, uninitialized copy of SDL;
this module resolves the libSDL2 path linked from kivy.core.window._window_sdl2
and rejects mappings where SDL_WasInit(0) does not match Kivy's subsystems.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from ctypes import CDLL, c_char_p, c_int, c_uint, c_void_p
from ctypes.util import find_library
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

SDL_INIT_VIDEO = 0x00000020
SDL_INIT_JOYSTICK = 0x00000200
_KIVY_SDL_BITS = SDL_INIT_VIDEO | SDL_INIT_JOYSTICK

_sdl2_dll: Optional[Any] = None  # CDLL, or False after permanent load failure
_joystick_slots_opened: int = 0 # Count of contiguous indices [0..n) we have successfully SDL_JoystickOpen'd.


def _kivy_window_module_path() -> Optional[str]:
    try:
        from kivy.core.window import _window_sdl2 as mod
    except ImportError:
        return None
    return str(Path(mod.__file__).resolve())


def _libsdl2_paths_linked_by_kivy(so_path: str) -> list[str]:
    """libSDL2 paths listed for `_window_sdl2` (same mapping as Kivy's SDL_Init)."""
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
        if sys.platform == "darwin":
            r = subprocess.run(
                ["otool", "-L", so_path],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            out: list[str] = []
            for raw in (r.stdout or "").splitlines():
                line = raw.strip()
                if "libSDL2" not in line:
                    continue
                if line.endswith(".dylib") or "/SDL2.framework/" in line:
                    out.append(line.split()[0])
            return out
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
    if so:
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


def _load_sdl2() -> Optional[Any]:
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
    sdl.SDL_JoystickOpen.argtypes = [c_int]
    sdl.SDL_JoystickOpen.restype = c_void_p
    sdl.SDL_GetError.argtypes = []
    sdl.SDL_GetError.restype = c_char_p


def ensure_sdl_joysticks_open() -> None:
    """Refresh joystick state; open device indices that appeared since last run.

    SDL2 increments an internal refcount each time SDL_JoystickOpen hits an
    already-open joystick, so we only call it for new indices (and retry from
    the first not-yet-open index after an unplug reduces ``SDL_NumJoysticks``).
    """
    global _joystick_slots_opened
    sdl = _load_sdl2()
    if sdl is None:
        return
    try:
        _bind_sdl_joystick_api(sdl)
        inited = sdl.SDL_WasInit(0)
        if not (inited & SDL_INIT_JOYSTICK):
            logger.warning(
                "Gamepad SDL: joystick subsystem not initialized (WasInit=0x%x)",
                inited,
            )
            return
        sdl.SDL_JoystickUpdate()
        n = int(sdl.SDL_NumJoysticks())
        if n < _joystick_slots_opened:
            _joystick_slots_opened = n
        i = _joystick_slots_opened
        while i < n:
            if not sdl.SDL_JoystickOpen(i):
                err = sdl.SDL_GetError()
                detail = err.decode("utf-8", "replace") if err else ""
                logger.warning(
                    "Gamepad SDL: SDL_JoystickOpen(%d) failed: %r",
                    i,
                    detail,
                )
                break
            i += 1
        _joystick_slots_opened = i
    except Exception:
        logger.warning("Gamepad SDL: error opening joysticks", exc_info=True)
