"""Tests for firmware version parsing in Utils.digitize_v."""

import json

from carveracontroller.Utils import digitize_v, parse_github_release


def test_digitize_v_handles_community_rc_versions():
    assert digitize_v("2.2.0") == digitize_v("2.2.0-RC1")
    assert digitize_v("2.2.0") == digitize_v("2.2.0c-RC1")
    assert digitize_v("2.2.0-RC1") >= digitize_v("2.2.0")
    assert digitize_v("2.1.0-RC1") < digitize_v("2.2.0")


def test_digitize_v_empty_version():
    assert digitize_v("") == 0


class TestParseGithubRelease:
    def test_parses_dict_payload(self):
        version, notes = parse_github_release({"tag_name": "v2.1.0", "body": "notes here"})
        assert version == "2.1.0"
        assert notes == "notes here"

    def test_parses_json_string_and_bytes(self):
        payload = json.dumps({"tag_name": "v2.1.0c", "body": "fw notes"})
        assert parse_github_release(payload) == ("2.1.0c", "fw notes")
        assert parse_github_release(payload.encode()) == ("2.1.0c", "fw notes")

    def test_tag_without_v_prefix(self):
        assert parse_github_release({"tag_name": "2.0.0", "body": ""}) == ("2.0.0", "")

    def test_falls_back_to_name_when_tag_missing(self):
        assert parse_github_release({"name": "v1.2.3", "body": "x"}) == ("1.2.3", "x")

    def test_missing_or_null_body_yields_empty_notes(self):
        assert parse_github_release({"tag_name": "v1.0.0"}) == ("1.0.0", "")
        assert parse_github_release({"tag_name": "v1.0.0", "body": None}) == ("1.0.0", "")

    def test_invalid_payloads_yield_empty_result(self):
        assert parse_github_release("not json") == ("", "")
        assert parse_github_release(b"\xff\xfe") == ("", "")
        assert parse_github_release(["list"]) == ("", "")
        assert parse_github_release({"message": "Not Found"}) == ("", "")
        assert parse_github_release({"tag_name": 123}) == ("", "")
