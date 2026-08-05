"""Probe lifecycle management: phased sending, animation, timeout, and run-token tracking."""

from __future__ import annotations

import time
from collections.abc import Callable

from kivy.clock import Clock

from carveracontroller.translation import tr

from ..core.gcode import ProbeProgram

_PROBE_ANIM_FRAMES = ("◐", "◓", "◑", "◒")
_PROBE_TIMEOUT_S = 30.0
_POLL_S = 0.2  # How often to check the machine state.
_SETUP_SETTLE_S = 1.0  # How long to wait after setup before sending the probe.
_MOTION_GRACE_S = 3.0  # How long to treat Idle as "probe done" if Run was never seen.

_PHASE_SETUP = "setup"
_PHASE_PROBE = "probe"
_PHASE_RESULT = "result"


class ProbeRunner:
    """Runs one probe operation, sending setup, probe motion and result tail in turn."""

    def __init__(
        self,
        *,
        set_is_probing: Callable[[bool], None],
        set_status_text: Callable[[str], None],
        on_is_probing_changed: Callable[[], None],
        controller_abort: Callable[[], None],
        get_state: Callable[[], str],
        execute_line: Callable[[str], None],
        on_aborted: Callable[[str], None] | None = None,
    ) -> None:
        self._set_is_probing = set_is_probing
        self._set_status_text = set_status_text
        self._on_is_probing_changed = on_is_probing_changed
        self._controller_abort = controller_abort
        self._get_state = get_state
        self._execute_line = execute_line
        self._on_aborted = on_aborted

        self._gen: int = 0
        self._active_token: int | None = None
        self._anim_event = None
        self._timeout_event = None
        self._poll_event = None
        self._anim_frame: int = 0

        self._program: ProbeProgram | None = None
        self._phase: str = _PHASE_SETUP
        self._phase_started_at: float = 0.0
        self._saw_busy: bool = False

    def start(self, program: ProbeProgram) -> int:
        """Start a probe run. Returns the run token for deferred validation."""
        self._gen += 1
        self._active_token = self._gen
        self._anim_frame = 0
        self._program = program
        self._phase = _PHASE_SETUP
        self._phase_started_at = time.time()
        self._saw_busy = False
        self._set_is_probing(True)
        self._tick_status()

        for line in program.setup:
            self._execute_line(line)

        if self._anim_event is not None:
            self._anim_event.cancel()
        self._anim_event = Clock.schedule_interval(self._tick_anim, 0.18)

        if self._timeout_event is not None:
            self._timeout_event.cancel()
        saved_token = self._active_token
        self._timeout_event = Clock.schedule_once(
            lambda _dt, t=saved_token: self._on_timeout(_dt, t),
            _PROBE_TIMEOUT_S,
        )

        if self._poll_event is not None:
            self._poll_event.cancel()
        self._poll_event = Clock.schedule_interval(self._poll, _POLL_S)

        self._on_is_probing_changed()
        return self._active_token

    def pre_complete(self) -> None:
        """Cancel the timeout immediately (call as soon as a result arrives).

        Safe to call from any thread; just cancels the Kivy Clock event.
        The actual probe state is updated later in ``complete()``.
        """
        if self._timeout_event is not None:
            self._timeout_event.cancel()
            self._timeout_event = None

    def complete(self) -> None:
        """Mark the current probe run as finished (success path)."""
        self._invalidate_token()
        self._clear_events()
        self._set_is_probing(False)
        self._set_status_text("")
        self._on_is_probing_changed()

    def cancel(self, *, abort_machine: bool = False) -> None:
        """Cancel the current probe run and optionally abort the machine."""
        self._invalidate_token()
        self._clear_events()
        if abort_machine and self._get_state() != "Idle":
            self._controller_abort()
        self._set_is_probing(False)
        self._set_status_text("")
        self._on_is_probing_changed()

    def abort(self, reason: str) -> None:
        """End the run early and report *reason* (timeout, error or bad machine state)."""
        if self._active_token is None:
            return
        self.cancel(abort_machine=True)
        if self._on_aborted is not None:
            self._on_aborted(reason)

    def shutdown(self) -> None:
        """Silently cancel all events without firing callbacks (use on popup dismiss)."""
        self._invalidate_token()
        self._clear_events()

    def is_token_valid(self, token: int | None) -> bool:
        """Return True if *token* matches the currently active run."""
        return token is not None and token == self._active_token

    def get_active_token(self) -> int | None:
        """Return the current run token, or None if not probing."""
        return self._active_token

    def _invalidate_token(self) -> None:
        self._gen += 1
        self._active_token = None

    def _clear_events(self) -> None:
        if self._anim_event is not None:
            self._anim_event.cancel()
            self._anim_event = None
        if self._timeout_event is not None:
            self._timeout_event.cancel()
            self._timeout_event = None
        if self._poll_event is not None:
            self._poll_event.cancel()
            self._poll_event = None
        self._program = None

    def _poll(self, _dt=None) -> None:
        """Watch the machine state and hand it the next phase when it is ready."""
        if self._active_token is None or self._program is None:
            return

        # A probe cycle should only ever reports Idle or Run
        # If we receive anything else, it means the probe stopped early and the run has to be abandoned.
        state = self._get_state()
        if state not in ("Idle", "Run"):
            self.abort(tr._("Probing failed: Unexpected machine state \"%s\".") % state)
            return

        now = time.time()
        if self._phase == _PHASE_SETUP:
            if state == "Idle" and (now - self._phase_started_at) >= _SETUP_SETTLE_S:
                self._execute_line(self._program.probe)
                self._phase = _PHASE_PROBE
                self._phase_started_at = now
        elif self._phase == _PHASE_PROBE:
            if state != "Idle":
                self._saw_busy = True
            elif self._saw_busy or (now - self._phase_started_at) >= _MOTION_GRACE_S:
                for line in self._program.tail:
                    self._execute_line(line)
                self._phase = _PHASE_RESULT
        # In _PHASE_RESULT the poll only keeps watching the state
        # We stop polling when the M118 capture ends the run through pre_complete()/complete().
    def _tick_anim(self, _dt=None) -> None:
        self._anim_frame = (self._anim_frame + 1) % len(_PROBE_ANIM_FRAMES)
        self._tick_status()

    def _tick_status(self) -> None:
        frame = _PROBE_ANIM_FRAMES[self._anim_frame % len(_PROBE_ANIM_FRAMES)]
        self._set_status_text(f"{frame}  {tr._('Probing in progress ...')}")

    def _on_timeout(self, _dt=None, run_token: int | None = None) -> None:
        if self._active_token is None:
            return
        if run_token is None or run_token != self._active_token:
            return
        self.abort(tr._("Probe timed out."))
