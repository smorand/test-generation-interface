"""The containment primitive, tested on the payloads the class sweep found.

These are unit tests and they prove the function, not the system. The proof that the
system is closed is the E2E suite, which drives real routes with the same payloads.
"""

from __future__ import annotations

import pytest

from tgi.services.paths import (
    InvalidIdentifier,
    safe_basename,
    validated_project_id,
    validated_test_id,
    validated_version,
)


class TestSafeBasename:
    def test_a_traversal_keeps_only_its_last_segment(self) -> None:
        # Basename first: flattening to etc_passwd.md would keep the traversal in the name
        assert safe_basename("../../../etc/passwd.md") == "passwd.md"
        assert safe_basename("../../escaped.md") == "escaped.md"
        assert safe_basename("/absolu/evil.md") == "evil.md"

    def test_the_windows_separator_counts_too(self) -> None:
        assert safe_basename("..\\..\\..\\etc\\passwd.md") == "passwd.md"
        assert safe_basename("..\\..\\evil.md") == "evil.md"

    def test_a_legitimate_unicode_name_survives_untouched(self) -> None:
        # The emoji is category So: a whitelist of letters and digits would drop it
        assert safe_basename("spécification_été_📄.docx") == "spécification_été_📄.docx"

    def test_a_degenerate_basename_becomes_document(self) -> None:
        for raw in (".", "..", "...", "/", "\\", "", "   ", '<>:"|?*'):
            assert safe_basename(raw) == "document", raw

    def test_trailing_dots_and_spaces_are_stripped_because_ntfs_ignores_them(self) -> None:
        assert safe_basename(".. ") == "document"
        assert safe_basename("evil.md.") == "evil.md"
        assert safe_basename("evil.md   ") == "evil.md"

    def test_a_windows_device_name_is_prefixed_rather_than_opened(self) -> None:
        # Reading CON through a synchronous open blocks the event loop for every request
        assert safe_basename("CON") == "_CON"
        assert safe_basename("NUL") == "_NUL"
        assert safe_basename("COM1.md") == "_COM1.md"
        assert safe_basename("con.MD") == "_con.MD"
        assert safe_basename("CONIN$") == "_CONIN$"
        assert safe_basename("COM¹") == "_COM¹"

    def test_a_control_character_cannot_reach_the_filesystem(self) -> None:
        assert safe_basename("evil\x00.md") == "evil_.md"
        assert safe_basename("evil\n.md") == "evil_.md"


class TestValidatedProjectId:
    def test_both_the_legacy_uuid_and_the_short_form_are_accepted(self) -> None:
        # Narrowing to either one would make every project of the other shape unreachable
        uuid4 = "e1f2a3b4-c5d6-4e7f-8a9b-0c1d2e3f4a5b"
        assert validated_project_id(uuid4) == uuid4
        assert validated_project_id("0123456789ab") == "0123456789ab"

    @pytest.mark.parametrize(
        "raw",
        [
            "..",
            "../..",
            "0123456789ab\n",  # $ matches before a final newline, %0A in a URL
            "0123456789aB",  # uppercase is outside the class
            "short",
            "g123456789ab",
            "0123456789a",  # 11 hex characters: the lower bound is a bound, not decoration
            "0123456789abcdef0123456789abcdef01234",  # 37, one over
            "",
        ],
    )
    def test_anything_else_is_refused_before_it_composes_a_path(self, raw: str) -> None:
        with pytest.raises(InvalidIdentifier):
            validated_project_id(raw)


class TestValidatedVersion:
    def test_a_numbered_version_is_accepted(self) -> None:
        assert validated_version("v1") == "v1"
        assert validated_version("v10") == "v10"

    @pytest.mark.parametrize("raw", ["..", "v0", "v01", "v", "1", "v1\n", ""])
    def test_anything_else_is_refused(self, raw: str) -> None:
        with pytest.raises(InvalidIdentifier):
            validated_version(raw)


class TestValidatedTestId:
    def test_a_schema_shaped_id_is_accepted(self) -> None:
        assert validated_test_id("TEST-0001") == "TEST-0001"
        # Wider than the schema on purpose, so a hand-written id in an existing state resolves
        assert validated_test_id("TEST_1.2") == "TEST_1.2"

    @pytest.mark.parametrize(
        "raw",
        [
            "..",
            "...",
            ".hidden",  # a leading dot addresses a hidden file
            "..\\..\\evil",
            "../../evil",
            "TEST-0001\n",
            "",
        ],
    )
    def test_anything_else_is_refused(self, raw: str) -> None:
        with pytest.raises(InvalidIdentifier):
            validated_test_id(raw)


class TestInvalidIdentifier:
    def test_it_is_a_value_error_and_not_a_missing_file(self) -> None:
        # Were it a FileNotFoundError, callers already catching that one would report a
        # refused identifier as a missing project: the same answer for two different facts
        assert issubclass(InvalidIdentifier, ValueError)
        assert not issubclass(InvalidIdentifier, FileNotFoundError)
