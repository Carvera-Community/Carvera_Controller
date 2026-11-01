from carveracontroller.protocols.framing import (
    PTYPE_CTRL_MULTI,
    PTYPE_FILE_MD5,
    PTYPE_LOAD_ERROR,
    PTYPE_LOAD_FINISH,
    PTYPE_LOAD_INFO,
    PTYPE_NORMAL_INFO,
    PTYPE_STATUS_RES,
    build_frame,
    validate_packet_data,
)
from carveracontroller.protocols.makera import MakeraProtocol
from carveracontroller.protocols.messages import MessageKind
from carveracontroller.protocols.session import ProtocolSession


def _ctrl_payloads(encoded: bytes) -> list[bytes]:
    payloads = []
    offset = 0
    while offset < len(encoded):
        assert encoded[offset : offset + 2] == b"\x86\x68"
        length = int.from_bytes(encoded[offset + 2 : offset + 4], "big")
        frame_end = offset + 4 + length + 2
        parsed = validate_packet_data(encoded[offset + 2 : frame_end - 2])
        assert parsed is not None
        assert parsed.ptype == PTYPE_CTRL_MULTI
        payloads.append(parsed.payload)
        offset = frame_end
    return payloads


def test_encode_realtime_and_command():
    proto = MakeraProtocol()
    frame = proto.encode_realtime(ord("?"))
    assert frame[:2] == b"\x86\x68"
    assert frame[-2:] == b"\x55\xaa"

    cmd = proto.encode_command(b"version\n")
    assert cmd[:2] == b"\x86\x68"
    # Trailing newlines must be stripped from CTRL_MULTI payloads (OEM behavior).
    assert b"version\n" not in cmd
    assert b"version" in cmd

    baud = proto.encode_command(b"baud 230400\n")
    assert b"230400\n" not in baud
    assert b"baud 230400" in baud

    file_cmd = proto.encode_file_command(b"upload /sd/a.nc")
    assert file_cmd[:2] == b"\x86\x68"
    # File-start frames keep the trailing newline.
    assert b"upload /sd/a.nc\n" in file_cmd


def test_encode_command_sends_each_line_as_its_own_frame():
    proto = MakeraProtocol()
    payloads = _ctrl_payloads(proto.encode_command(b"help\nhelp\n"))
    assert payloads == [b"help", b"help"]

    payloads = _ctrl_payloads(proto.encode_command(b"config-set sd foo bar\r\nversion"))
    assert payloads == [b"config-set sd foo bar", b"version"]
    assert all(b"\n" not in payload and b"\r" not in payload for payload in payloads)


def test_feed_status_frame():
    proto = MakeraProtocol()
    payload = b"<Idle|MPos:1,2,3>"
    frame = build_frame(PTYPE_STATUS_RES, payload)
    msgs = proto.feed(frame)
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == payload.decode()


def test_feed_normal_info_and_load():
    proto = MakeraProtocol()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"ok\r\n"))
    assert msgs[0].kind == MessageKind.LINE
    assert "ok" in msgs[0].text

    msgs = proto.feed(build_frame(PTYPE_LOAD_INFO, b"file.nc\n"))
    assert msgs[0].kind == MessageKind.LOAD_CHUNK
    assert "file.nc" in msgs[0].text


def test_feed_normal_info_buffers_until_newline():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"hel")) == []
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"lo")) == []

    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" world\r\n"))
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == "hello world\r"


def test_feed_normal_info_splits_on_embedded_newlines():
    proto = MakeraProtocol()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"one\ntwo\npartial"))
    assert [m.text for m in msgs] == ["one", "two"]

    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" line\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "partial line"


def test_feed_normal_info_reset_discards_partial_line():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"leftover")) == []
    proto.reset()
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b"fresh\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "fresh"


def test_session_emits_one_mdi_line_for_buffered_normal_info():
    session = ProtocolSession()
    session.select("makera")
    assert session.feed(build_frame(PTYPE_NORMAL_INFO, b"Build version: ")) == []
    assert session.feed(build_frame(PTYPE_NORMAL_INFO, b"edge-")) == []
    msgs = session.feed(build_frame(PTYPE_NORMAL_INFO, b"123\r\n"))
    assert len(msgs) == 1
    assert msgs[0].kind == MessageKind.LINE
    assert msgs[0].text == "Build version: edge-123"


def test_feed_status_is_not_held_by_normal_info_buffer():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_NORMAL_INFO, b"partial")) == []
    msgs = proto.feed(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    assert len(msgs) == 1
    assert msgs[0].text == "<Idle>"
    msgs = proto.feed(build_frame(PTYPE_NORMAL_INFO, b" line\n"))
    assert len(msgs) == 1
    assert msgs[0].text == "partial line"


def test_feed_load_finish_and_error():
    proto = MakeraProtocol()
    assert proto.feed(build_frame(PTYPE_LOAD_FINISH, b"done"))[0].kind == MessageKind.LOAD_EOF
    assert proto.feed(build_frame(PTYPE_LOAD_ERROR, b"err"))[0].kind == MessageKind.LOAD_ERROR


def test_feed_rejects_bad_footer():
    proto = MakeraProtocol()
    frame = bytearray(build_frame(PTYPE_STATUS_RES, b"<Idle>"))
    frame[-1] = 0x00
    assert proto.feed(bytes(frame)) == []


def test_feed_byte_at_a_time():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_STATUS_RES, b"<Run>")
    msgs = []
    for b in frame:
        msgs.extend(proto.feed(bytes([b])))
    assert len(msgs) == 1
    assert msgs[0].text == "<Run>"


def test_file_transfer_frames_ignored_on_control_channel():
    proto = MakeraProtocol()
    frame = build_frame(PTYPE_FILE_MD5, b"3bc28b19cfca32e413fd9029000117a3")
    assert proto.feed(frame) == []
