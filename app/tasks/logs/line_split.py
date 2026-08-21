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

Two shapes are offered. :func:`split_complete_lines` splits a buffer the caller
already holds whole, which is what a fetch-per-cycle consumer needs.
:class:`WithheldLineBuffer` owns the withheld bytes across frames instead, so a
streaming consumer pays for the bytes each frame delivered rather than for the
whole buffer it is holding.
"""

from typing import NamedTuple


class LineSplit(NamedTuple):
    """Carry the complete lines and withheld remainder from one buffer split.

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


class LineRelease(NamedTuple):
    """Carry what one appended frame released from a :class:`WithheldLineBuffer`.

    :param complete: Every byte released for anonymization, or ``b""`` when the
        frame completed no line.
    :param forced: ``True`` when the ceiling flushed an un-terminated buffer.
    """

    complete: bytes
    forced: bool


def _exceeds_ceiling(withheld: int, max_withheld: int | None) -> bool:
    """Return whether withholding ``withheld`` bytes would breach the ceiling.

    Shared by both shapes in this module so the live and persisted paths cannot
    disagree about a remainder of exactly ``max_withheld`` bytes.

    :param withheld: The raw byte length that would be withheld.
    :param max_withheld: The ceiling, or ``None`` to disable it.
    :return: ``True`` when the length is strictly greater than the ceiling.
    """
    return max_withheld is not None and withheld > max_withheld


def split_complete_lines(buf: bytes, max_withheld: int | None = None) -> LineSplit:
    r"""Split ``buf`` at the last line terminator.

    A carriage return is treated as a terminator alongside the newline so that
    ``\r``-driven progress output does not stall un-flushed on the live tail.
    Both are ASCII (< 0x80), so neither can appear inside a multi-byte UTF-8
    sequence -- splitting on either is inherently codepoint-safe.

    When ``max_withheld`` is set and the trailing remainder would exceed that
    byte length, the whole ``buf`` is returned as ``complete`` with an empty
    remainder and ``forced=True``. The buffer is returned intact rather than
    cut at ``max_withheld`` so no new mid-codepoint split is introduced, but
    ``buf`` may itself end mid-codepoint; the caller accepts a redaction miss
    and one replacement character at exactly that boundary.

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
    if _exceeds_ceiling(len(remainder), max_withheld):
        return LineSplit(buf, b"", forced=True)
    return LineSplit(complete, remainder, forced=False)


class WithheldLineBuffer:
    r"""Hold bytes withheld from anonymization until a terminator completes them.

    :meth:`append` is the only way bytes enter the buffer, and it releases every
    line the arriving frame completed — so what stays withheld is always
    terminator-free. That invariant is what lets each frame search only the
    bytes it delivered: any terminator must lie in them, and a scan starting at
    the pre-append length sees everything a whole-buffer scan would. The frames
    that release nothing therefore cost their own bytes instead of the megabyte
    they may be sitting on.
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        """Start with nothing withheld."""
        self._buf = bytearray()

    def __len__(self) -> int:
        """Return the raw byte length currently withheld.

        :return: The number of withheld bytes.
        """
        return len(self._buf)

    def __bytes__(self) -> bytes:
        """Return a copy of the withheld bytes.

        :return: The withheld bytes.
        """
        return bytes(self._buf)

    def append(self, data: bytes, max_withheld: int | None = None) -> LineRelease:
        r"""Add one frame's bytes and release whatever lines it completed.

        A carriage return terminates a line alongside the newline so that
        ``\r``-driven progress output does not stall un-flushed. Both are ASCII
        (< 0x80), so neither can appear inside a multi-byte UTF-8 sequence --
        splitting on either is inherently codepoint-safe.

        The ceiling is taken per call rather than per buffer because it is a
        runtime-tunable setting: lowering it must release a buffer that is
        already over the new value on the very next frame.

        :param data: The frame's raw (pre-anonymization) bytes.
        :param max_withheld: Optional ceiling on the raw byte length that may
            stay withheld awaiting a terminator. A remainder of exactly this
            length is still withheld; only a longer one forces a flush.
            ``None`` disables the ceiling.
        :return: A :class:`LineRelease` whose ``complete`` bytes the caller must
            anonymize and emit, empty when the frame completed no line.
        """
        scan_from = len(self._buf)
        self._buf += data
        index = max(
            self._buf.rfind(b"\n", scan_from), self._buf.rfind(b"\r", scan_from)
        )
        cut = index + 1
        if _exceeds_ceiling(len(self._buf) - cut, max_withheld):
            return LineRelease(self.drain(), forced=True)
        if not cut:
            return LineRelease(b"", forced=False)
        complete = bytes(self._buf[:cut])
        del self._buf[:cut]
        return LineRelease(complete, forced=False)

    def drain(self) -> bytes:
        """Release everything still withheld, emptying the buffer.

        :return: The withheld bytes, or ``b""`` when nothing was withheld.
        """
        remainder = bytes(self._buf)
        self._buf.clear()
        return remainder
