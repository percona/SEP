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

from app.tasks.logs.line_split import split_complete_lines


class TestSplitCompleteLines:
    """Test ``split_complete_lines``."""

    def test_empty_buffer(self):
        """Assert an empty buffer yields two empty byte strings."""
        assert split_complete_lines(b"") == (b"", b"")

    def test_no_terminator_withholds_everything(self):
        """Assert a buffer with no line terminator is withheld whole."""
        assert split_complete_lines(b"card=4111") == (b"", b"card=4111")

    def test_single_newline_terminated_line(self):
        """Assert a fully terminated line leaves no remainder."""
        assert split_complete_lines(b"line\n") == (b"line\n", b"")

    def test_trailing_partial_after_newline(self):
        """Assert bytes after the last newline are the withheld remainder."""
        assert split_complete_lines(b"done\ncard=41") == (b"done\n", b"card=41")

    def test_multiple_lines_split_at_last_terminator(self):
        """Assert the split lands after the last terminator, not the first."""
        assert split_complete_lines(b"a\nb\nc") == (b"a\nb\n", b"c")

    def test_carriage_return_is_a_terminator(self):
        r"""Assert a lone ``\r`` (progress output) terminates a line so it flushes."""
        assert split_complete_lines(b"progress\rmore") == (b"progress\r", b"more")

    def test_crlf_splits_after_the_newline(self):
        r"""Assert ``\r\n`` keeps both bytes in the complete portion."""
        assert split_complete_lines(b"a\r\nb") == (b"a\r\n", b"b")

    def test_multibyte_codepoint_before_terminator_intact(self):
        """Assert a multi-byte codepoint just before the newline is not corrupted."""
        buf = "café\n".encode() + b"tail"
        complete, remainder = split_complete_lines(buf)
        assert complete == "café\n".encode()
        assert remainder == b"tail"
        complete.decode("utf-8")  # no UnicodeDecodeError

    def test_multibyte_codepoint_in_withheld_remainder_intact(self):
        """Assert a multi-byte codepoint in the remainder is measured whole.

        The split lands on the ASCII newline boundary, so the remainder's raw
        byte length is exact and re-decodes cleanly — the property the Nomad
        cursor rollback relies on.
        """
        remainder_text = "café=x"
        buf = b"first\n" + remainder_text.encode()
        complete, remainder = split_complete_lines(buf)
        assert complete == b"first\n"
        assert remainder == remainder_text.encode()
        assert len(remainder) == len(remainder_text.encode("utf-8"))
        remainder.decode("utf-8")  # no UnicodeDecodeError
