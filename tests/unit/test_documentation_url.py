"""Documentation site selection for stable, pre-release, and date-based builds."""

from carveracontroller.documentation import (
    DOCS_BASE_DEV,
    DOCS_BASE_STABLE,
    documentation_base,
    resolve_documentation_url,
)
from carveracontroller.updater.version import parse_version

CONTROLLER_DOCS = "https://carvera-community.gitbook.io/docs/controller/"
ANCHORED_DOCS = "https://carvera-community.gitbook.io/docs/controller/features/pendant-support#linux"


def test_stable_release_keeps_docs_base():
    for version in ("2.2.0", "v2.2.0", "2.1.0c", "99.0.0", ""):
        assert documentation_base(version) == DOCS_BASE_STABLE
        assert resolve_documentation_url(CONTROLLER_DOCS, version) == CONTROLLER_DOCS


def test_unversioned_placeholder_uses_dev_docs():
    for version in ("0.0.0", "v0.0.0"):
        assert documentation_base(version) == DOCS_BASE_DEV
        assert resolve_documentation_url(CONTROLLER_DOCS, version) == DOCS_BASE_DEV + "/controller/"
    assert not parse_version("v0.0.0").is_stable_release


def test_prerelease_tag_uses_dev_docs():
    for version in (
        "2.2.0-RC1",
        "v2.2.0-RC3",
        "2.1.0c-RC2",
        "1.0.0-BETA2",
        "3.1.0-ALPHA",
        "1.2.3-DEV",
        "2.2.0-nightly",
    ):
        assert documentation_base(version) == DOCS_BASE_DEV


def test_date_based_major_uses_dev_docs():
    assert documentation_base("100.0.0") == DOCS_BASE_DEV
    assert documentation_base("2026.9.26") == DOCS_BASE_DEV
    assert parse_version("2026.9.26") is not None
    assert not parse_version("2026.9.26").is_stable_release
    assert parse_version("2.2.0").is_stable_release
    assert not parse_version("2.2.0-RC1").is_stable_release


def test_resolve_preserves_path_and_anchor():
    assert resolve_documentation_url(CONTROLLER_DOCS, "2.2.0-RC1") == DOCS_BASE_DEV + "/controller/"
    assert resolve_documentation_url(ANCHORED_DOCS, "2026.1.0") == (
        DOCS_BASE_DEV + "/controller/features/pendant-support#linux"
    )
    assert resolve_documentation_url(DOCS_BASE_STABLE, "2.2.0") == DOCS_BASE_STABLE
    assert resolve_documentation_url(DOCS_BASE_STABLE, "2.2.0-RC1") == DOCS_BASE_DEV
    assert resolve_documentation_url("https://example.test/other", "2026.1.0") == "https://example.test/other"
