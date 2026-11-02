"""The Controller's side of the Upload API: readiness from the machine state, uploads through the
same ``uploadLocalFile`` path the file browser uses, and notices in the Controller's log."""

from __future__ import annotations

import logging
from typing import Callable

from kivy.app import App
from kivy.clock import Clock

from carveracontroller.CNC import CNC
from carveracontroller.Controller import NOT_CONNECTED, Controller

from .api import UploadOutcome

logger = logging.getLogger(__name__)


class MakeraBridge:
    """Adapts the ``Makera`` root widget to :class:`~.api.MachineBridge`."""

    def __init__(self, makera):
        self.makera = makera

    def readiness(self) -> tuple[bool, str]:
        m = self.makera
        state = CNC.vars.get("state", NOT_CONNECTED)
        controller = getattr(m, "controller", None)
        if controller is None or state == NOT_CONNECTED or not getattr(controller, "stream", None):
            return False, "not connected to a machine"
        app = App.get_running_app()
        if app is not None and getattr(app, "playing", False):
            return False, "a job is running"
        if getattr(m, "uploading", False) or getattr(m, "downloading", False) or getattr(controller, "sendNUM", 0):
            return False, "another file transfer is in progress"
        if getattr(m, "_batch_kind", None):
            return False, "a batch transfer is in progress"
        if state != "Idle":
            return False, f"machine is {state}"
        return True, ""

    def machine_name(self) -> str:
        return str(getattr(self.makera, "past_machine_addr", "") or "")

    def upload(self, local_path: str, remote_dir: str, done: Callable[[str, str], None]) -> None:
        # Kivy UI state (progress popup, file list) must be touched on the main thread. Check
        # readiness again there: the operator may have started something since the worker looked.
        def start(_dt):
            ready, reason = self.readiness()
            if not ready:
                done(UploadOutcome.BUSY, reason)
                return

            def finished(result, remotename):
                if result:
                    done(UploadOutcome.OK, f"uploaded to {remotename}")
                elif result is None:
                    done(UploadOutcome.FAILED, "upload cancelled in the Controller")
                else:
                    done(UploadOutcome.FAILED, "the machine reported an upload error")

            try:
                self.makera.uploadLocalFile(
                    local_path,
                    firmware=False,
                    remote_dir=remote_dir,
                    on_finished=finished,
                    remember_local_dir=False,
                )
            except Exception as exc:
                logger.exception("Upload API upload failed to start")
                done(UploadOutcome.FAILED, str(exc))

        Clock.schedule_once(start, 0)

    def notify(self, message: str) -> None:
        controller = getattr(self.makera, "controller", None)
        if controller is not None:
            controller.log.put((Controller.MSG_NORMAL, message))
        logger.info(message)
