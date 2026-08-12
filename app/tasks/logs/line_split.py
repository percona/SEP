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

"""Split log bytes into complete lines and a withheld trailing remainder.

Anonymization must see whole lines: a PII token split across two fetched byte
chunks is never matched by Presidio and escapes redaction. Callers use this
helper to withhold the trailing partial line until later bytes complete it.

When a ``max_withheld`` ceiling is supplied and the trailing remainder would
exceed it, the whole buffer is flushed as complete instead. That accepts a
single redaction-boundary leak so an un-terminated line cannot stall log
persistence, stall the live viewer, or drive unbounded re-fetching.
"""

from typing import NamedTuple


class LineSplit(NamedTuple):
    """Result of splitting a buffer into complete lines and a withheld remainder.

    :param complete: Every byte up to and including the last line terminator,
        or the whole buffer when a forced flush fires.
    :param remainder: The trailing partial line to withhold, or ``b""`` when
        nothing is withheld (including after a forced flush).
    :param forced: ``True`` when the ceiling forced a flush of the whole
        buffer rather than withholding the remainder.
    """

    complete: bytes
    remainder: bytes
    forced: bool


def split_complete_lines(
    buf: bytes, max_withheld: int | None = None
) -> LineSplit:
    r"""Split ``buf`` at the last line terminator.

    A carriage return is treated as a terminator alongside the newline so that
    ``\r``-driven progress output does not stall un-flushed on the live tail.
    Both are ASCII (< 0x80), so neither can appear inside a multi-byte UTF-8
    sequence -- splitting on either is inherently codepoint-safe.

    When ``max_withheld`` is set and the trailing remainder would exceed that
    byte length, the whole ``buf`` is returned as ``complete`` with an empty
    remainder and ``forced=True``. Returning the buffer whole (rather than
    cutting at a byte position) preserves codepoint safety; the caller accepts
    a redaction miss at exactly that one boundary.

    :param buf: The raw (pre-anonymization) bytes fetched so far.
    :param max_withheld: Optional ceiling on the raw byte length that may be
        withheld awaiting a terminator. A remainder of exactly this length is
        still withheld; only a length strictly greater forces a flush. ``None``
        disables the ceiling (legacy unbounded withholding).
    :return: A :class:`LineSplit` of ``(complete, remainder, forced)`` where
        ``complete`` is every byte up to and including the last ``\n`` or
        ``\r`` and ``remainder`` is the trailing partial line to withhold.
        When ``buf`` holds no terminator the whole buffer is withheld as the
        remainder unless the ceiling forces a flush.
    """
    index = max(buf.rfind(b"\n"), buf.rfind(b"\r"))
    if index == -1:
        complete, remainder = b"", buf
    else:
        complete, remainder = buf[: index + 1], buf[index + 1 :]
    if max_withheld is not None and len(remainder) > max_withheld:
        return LineSplit(buf, b"", True)
    return LineSplit(complete, remainder, False)
