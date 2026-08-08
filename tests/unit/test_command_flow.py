"""Tests for the queued-command flow control used by the Controller."""

from carveracontroller.machine.command_flow import (
    ACK_TIMEOUT_S,
    MIN_SEND_GAP_S,
    CommandFlowControl,
)


class TestCommandFlowControl:
    def test_empty_queue_returns_none(self):
        flow = CommandFlowControl()
        assert flow.pop_ready(0.0) is None

    def test_first_command_releases_immediately(self):
        flow = CommandFlowControl()
        flow.enqueue("G0 X1\n")
        assert flow.pop_ready(0.0) == "G0 X1\n"

    def test_second_command_held_until_machine_is_heard(self):
        flow = CommandFlowControl()
        flow.enqueue("first\n")
        flow.enqueue("second\n")
        assert flow.pop_ready(0.0) == "first\n"
        # No response yet: held.
        assert flow.pop_ready(0.1) is None
        flow.note_receive()
        assert flow.pop_ready(0.1) == "second\n"

    def test_min_gap_applies_even_with_fast_responses(self):
        flow = CommandFlowControl()
        flow.enqueue("first\n")
        flow.enqueue("second\n")
        assert flow.pop_ready(0.0) == "first\n"
        flow.note_receive()
        # Response arrived, but not enough time has passed since the send.
        assert flow.pop_ready(MIN_SEND_GAP_S / 2) is None
        assert flow.pop_ready(MIN_SEND_GAP_S) == "second\n"

    def test_ack_timeout_releases_without_response(self):
        flow = CommandFlowControl()
        flow.enqueue("first\n")
        flow.enqueue("second\n")
        assert flow.pop_ready(0.0) == "first\n"
        assert flow.pop_ready(ACK_TIMEOUT_S - 0.01) is None
        assert flow.pop_ready(ACK_TIMEOUT_S) == "second\n"

    def test_commands_release_in_fifo_order(self):
        flow = CommandFlowControl()
        for cmd in ("a\n", "b\n", "c\n"):
            flow.enqueue(cmd)
        released = []
        now = 0.0
        while True:
            flow.note_receive()
            now += 1.0  # comfortably beyond MIN_SEND_GAP_S, immune to float drift
            cmd = flow.pop_ready(now)
            if cmd is None:
                break
            released.append(cmd)
        assert released == ["a\n", "b\n", "c\n"]

    def test_clear_drops_pending_commands_and_resets_state(self):
        flow = CommandFlowControl()
        flow.enqueue("first\n")
        flow.enqueue("second\n")
        assert flow.pop_ready(0.0) == "first\n"
        flow.clear()
        assert flow.pending() == 0
        # After clear, a new command releases immediately again.
        flow.enqueue("third\n")
        assert flow.pop_ready(0.0) == "third\n"

    def test_receive_before_send_does_not_leak_into_next_hold(self):
        flow = CommandFlowControl()
        flow.enqueue("first\n")
        flow.note_receive()
        assert flow.pop_ready(0.0) == "first\n"
        flow.enqueue("second\n")
        # The pre-send receive must not count as a response to "first".
        assert flow.pop_ready(0.1) is None

    def test_pending_counts_queued_commands(self):
        flow = CommandFlowControl()
        assert flow.pending() == 0
        flow.enqueue("a\n")
        flow.enqueue("b\n")
        assert flow.pending() == 2
