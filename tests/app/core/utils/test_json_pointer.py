# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Define tests for the RFC 6901 JSON Pointer helpers."""

import pytest

from app.core.utils.json_pointer import (
    JsonPointerResolutionError,
    parse_json_pointer,
    resolve_json_pointer,
    validate_json_pointer,
)

SAMPLE_DOCUMENT = {
    "result": {"sys_id": "abc123"},
    "items": [{"id": 1}, {"id": 2}],
    "a/b": "slash-key",
    "m~n": "tilde-key",
}


class TestValidateJsonPointer:
    """Cover RFC 6901 syntax validation."""

    @pytest.mark.parametrize(
        "pointer",
        ["", "/", "/result/sys_id", "/items/0/id", "/a~1b", "/m~0n", "/~0~1"],
    )
    def test_accepts_valid_pointer(self, pointer: str):
        """Return the pointer unchanged for the root, plain, and escaped forms."""
        assert validate_json_pointer(pointer) == pointer

    @pytest.mark.parametrize("pointer", ["a/b", "result", " /a"])
    def test_rejects_pointer_without_leading_slash(self, pointer: str):
        """Reject a non-empty pointer that does not start with a slash."""
        with pytest.raises(ValueError, match="must start with"):
            validate_json_pointer(pointer)

    @pytest.mark.parametrize("pointer", ["/a~2b", "/a~", "/~"])
    def test_rejects_bad_escape(self, pointer: str):
        """Reject a tilde that is not part of a ``~0`` or ``~1`` escape."""
        with pytest.raises(ValueError, match="escape"):
            validate_json_pointer(pointer)


class TestParseJsonPointer:
    """Cover tokenization and escape decoding."""

    @pytest.mark.parametrize(
        ("pointer", "expected"),
        [
            ("", ()),
            ("/", ("",)),
            ("/result/sys_id", ("result", "sys_id")),
            ("/a~1b", ("a/b",)),
            ("/m~0n", ("m~n",)),
            ("/items/0/id", ("items", "0", "id")),
            ("/~01", ("~1",)),
        ],
    )
    def test_splits_and_unescapes(self, pointer: str, expected: tuple[str, ...]):
        """Split a pointer into reference tokens with escapes decoded."""
        assert parse_json_pointer(pointer) == expected

    def test_rejects_malformed_pointer(self):
        """Reject a syntactically invalid pointer instead of tokenizing it."""
        with pytest.raises(ValueError, match="must start with"):
            parse_json_pointer("a/b")


class TestResolveJsonPointer:
    """Cover resolution against decoded JSON documents."""

    def test_root_pointer_returns_whole_document(self):
        """Return the document itself for the empty root pointer."""
        assert resolve_json_pointer(SAMPLE_DOCUMENT, "") is SAMPLE_DOCUMENT

    def test_resolves_nested_object_key(self):
        """Walk nested mappings by key."""
        assert resolve_json_pointer(SAMPLE_DOCUMENT, "/result/sys_id") == "abc123"

    def test_resolves_list_index(self):
        """Walk sequences by decimal index."""
        second_item_id = 2
        assert resolve_json_pointer(SAMPLE_DOCUMENT, "/items/1/id") == second_item_id

    def test_resolves_top_level_list_document(self):
        """Walk a document whose root is a JSON list."""
        assert resolve_json_pointer([{"id": "x"}], "/0/id") == "x"

    @pytest.mark.parametrize(
        ("pointer", "expected"),
        [("/a~1b", "slash-key"), ("/m~0n", "tilde-key")],
    )
    def test_resolves_escaped_keys(self, pointer: str, expected: str):
        """Match keys that contain a literal slash or tilde."""
        assert resolve_json_pointer(SAMPLE_DOCUMENT, pointer) == expected

    def test_unresolvable_key_names_token_and_position(self):
        """Name the failing token and its position without echoing the document."""
        document = {"secret_case_note": "customer data"}
        with pytest.raises(JsonPointerResolutionError) as excinfo:
            resolve_json_pointer(document, "/nope")

        message = str(excinfo.value)
        assert "nope" in message
        assert "0" in message
        assert "customer data" not in message
        assert "secret_case_note" not in message

    def test_traversal_into_scalar_is_rejected(self):
        """Reject a pointer that walks past a scalar value."""
        with pytest.raises(JsonPointerResolutionError, match="traverse"):
            resolve_json_pointer({"a": 1}, "/a/b")

    def test_non_integer_list_token_is_rejected(self):
        """Reject a non-numeric token against a sequence."""
        with pytest.raises(JsonPointerResolutionError, match="index"):
            resolve_json_pointer({"items": [1, 2]}, "/items/x")

    def test_out_of_range_list_index_is_rejected(self):
        """Reject an index past the end of a sequence."""
        with pytest.raises(JsonPointerResolutionError, match="index"):
            resolve_json_pointer({"items": [1]}, "/items/5")

    def test_string_is_not_traversed_as_a_sequence(self):
        """Reject indexing into a string value."""
        with pytest.raises(JsonPointerResolutionError, match="traverse"):
            resolve_json_pointer({"a": "xyz"}, "/a/0")
