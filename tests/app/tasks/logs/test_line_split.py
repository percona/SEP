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

"""Define tests for ``app.tasks.logs.line_split``."""

from app.tasks.logs.line_split import LineSplit, split_complete_lines


class TestSplitCompleteLines:
    """Test ``split_complete_lines``."""

    def test_empty_buffer(self):
        """Assert an empty buffer yields two empty byte strings."""
        assert split_complete_lines(b"") == LineSplit(b"", b"", False)

    def test_no_terminator_withholds_everything(self):
        """Assert a buffer with no line terminator is withheld whole."""
        assert split_complete_lines(b"card=4111") == LineSplit(b"", b"card=4111", False)

    def test_single_newline_terminated_line(self):
        """Assert a fully terminated line leaves no remainder."""
        assert split_complete_lines(b"line\n") == LineSplit(b"line\n", b"", False)

    def test_trailing_partial_after_newline(self):
        """Assert bytes after the last newline are the withheld remainder."""
        assert split_complete_lines(b"done\ncard=41") == LineSplit(
            b"done\n", b"card=41", False
        )

    def test_multiple_lines_split_at_last_terminator(self):
        """Assert the split lands after the last terminator, not the first."""
        assert split_complete_lines(b"a\nb\nc") == LineSplit(b"a\nb\n", b"c", False)

    def test_carriage_return_is_a_terminator(self):
        r"""Assert a lone ``\r`` (progress output) terminates a line so it flushes."""
        assert split_complete_lines(b"progress\rmore") == LineSplit(
            b"progress\r", b"more", False
        )

    def test_crlf_splits_after_the_newline(self):
        r"""Assert ``\r\n`` keeps both bytes in the complete portion."""
        assert split_complete_lines(b"a\r\nb") == LineSplit(b"a\r\n", b"b", False)

    def test_multibyte_codepoint_before_terminator_intact(self):
        """Assert a multi-byte codepoint just before the newline is not corrupted."""
        buf = "café\n".encode() + b"tail"
        split = split_complete_lines(buf)
        assert split.complete == "café\n".encode()
        assert split.remainder == b"tail"
        assert split.forced is False
        split.complete.decode("utf-8")  # no UnicodeDecodeError

    def test_multibyte_codepoint_in_withheld_remainder_intact(self):
        """Assert a multi-byte codepoint in the remainder is measured whole.

        The split lands on the ASCII newline boundary, so the remainder's raw
        byte length is exact and re-decodes cleanly — the property the Nomad
        cursor rollback relies on.
        """
        remainder_text = "café=x"
        buf = b"first\n" + remainder_text.encode()
        split = split_complete_lines(buf)
        assert split.complete == b"first\n"
        assert split.remainder == remainder_text.encode()
        assert split.forced is False
        assert len(split.remainder) == len(remainder_text.encode("utf-8"))
        split.remainder.decode("utf-8")  # no UnicodeDecodeError

    def test_remainder_below_ceiling_still_withheld(self):
        """Assert a remainder shorter than the ceiling is still withheld."""
        assert split_complete_lines(b"done\ncard=41", max_withheld=8) == LineSplit(
            b"done\n", b"card=41", False
        )

    def test_remainder_exactly_at_ceiling_still_withheld(self):
        """Assert a remainder equal to the ceiling is still withheld.

        The boundary is strictly greater-than: exactly ``max_withheld`` bytes
        must not force a flush.
        """
        remainder = b"card=41"  # 7 bytes
        assert split_complete_lines(
            b"done\n" + remainder, max_withheld=len(remainder)
        ) == LineSplit(b"done\n", remainder, False)

    def test_remainder_above_ceiling_forces_flush(self):
        """Assert a remainder longer than the ceiling flushes the whole buffer."""
        buf = b"done\ncard=4111"  # remainder is 9 bytes
        assert split_complete_lines(buf, max_withheld=8) == LineSplit(buf, b"", True)

    def test_no_terminator_above_ceiling_forces_flush(self):
        """Assert an un-terminated buffer longer than the ceiling is flushed whole."""
        buf = b"card=41111111"  # 13 bytes, no terminator
        assert split_complete_lines(buf, max_withheld=8) == LineSplit(buf, b"", True)

    def test_no_ceiling_never_forces_flush(self):
        """Assert omitting ``max_withheld`` preserves unbounded withholding."""
        buf = b"x" * 100
        assert split_complete_lines(buf) == LineSplit(b"", buf, False)

    def test_forced_flush_preserves_mid_codepoint_bytes(self):
        """Assert a forced flush returns the buffer whole, not a mid-codepoint cut.

        Cutting at a byte position could split a multi-byte UTF-8 sequence;
        returning ``buf`` intact keeps the module's codepoint-safety guarantee.
        """
        # "é" is two UTF-8 bytes (0xc3 0xa9); an unterminated buffer ending
        # mid-codepoint must still flush as the original bytes.
        buf = b"cafe\xc3"  # incomplete "é"
        split = split_complete_lines(buf, max_withheld=3)
        assert split == LineSplit(buf, b"", True)
        assert split.complete is buf or split.complete == buf
