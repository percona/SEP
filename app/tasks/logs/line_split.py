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

:func:`split_complete_lines` splits a buffer the caller already holds whole.
:class:`WithheldLineBuffer` owns the withheld bytes across successive frames
and releases what each frame completed.
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
    :param forced: ``True`` when the ceiling released the whole buffer, which
        includes any complete lines preceding the un-terminated tail.
    """

    complete: bytes
    forced: bool


def _last_terminator(buf: bytes | bytearray, start: int = 0) -> int:
    """Return the index of the last line terminator at or after ``start``.

    A carriage return terminates a line alongside the newline, so progress
    output that only ever returns the cursor still flushes. Both are ASCII, so
    neither can appear inside a multi-byte UTF-8 sequence and a split on either
    is codepoint-safe.

    :param buf: The bytes to scan.
    :param start: The offset to scan from; earlier bytes are not examined.
    :return: The index of the last terminator, or ``-1`` when the scanned range
        holds none.
    """
    return max(buf.rfind(b"\n", start), buf.rfind(b"\r", start))


def _exceeds_ceiling(withheld: int, max_withheld: int | None) -> bool:
    """Return whether withholding ``withheld`` bytes would breach the ceiling.

    :param withheld: The raw byte length that would be withheld.
    :param max_withheld: The ceiling, or ``None`` to disable it.
    :return: ``True`` when the length is strictly greater than the ceiling.
    """
    return max_withheld is not None and withheld > max_withheld


def split_complete_lines(buf: bytes, max_withheld: int | None = None) -> LineSplit:
    """Split ``buf`` at the last line terminator.

    When ``max_withheld`` is set and the trailing remainder would exceed that
    byte length, the whole ``buf`` is returned as ``complete`` with an empty
    remainder and ``forced=True``. Returning it intact introduces no new
    mid-codepoint split, though ``buf`` may itself end mid-codepoint; the
    caller accepts a redaction miss and one replacement character there.

    :param buf: The raw (pre-anonymization) bytes fetched so far.
    :param max_withheld: Optional ceiling on the raw byte length that may be
        withheld awaiting a terminator. A remainder of exactly this length is
        still withheld; only a length strictly greater forces a flush. ``None``
        disables the ceiling.
    :return: A :class:`LineSplit` whose ``complete`` runs to the last terminator
        and whose ``remainder`` is the trailing partial line to withhold. A
        ``buf`` holding no terminator is withheld whole unless the ceiling
        forces a flush.
    """
    cut = _last_terminator(buf) + 1
    remainder = buf[cut:]
    if _exceeds_ceiling(len(remainder), max_withheld):
        return LineSplit(buf, b"", forced=True)
    return LineSplit(buf[:cut], remainder, forced=False)


class WithheldLineBuffer:
    """Hold bytes withheld from anonymization until a terminator completes them.

    :meth:`append` is the only way bytes enter the buffer and it releases every
    line the arriving frame completed, so whatever stays withheld holds no
    terminator. Each frame therefore costs a scan of its own bytes, not of the
    whole buffer behind it.
    """

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    def __len__(self) -> int:
        """Return the raw byte length currently withheld."""
        return len(self._buf)

    def append(self, data: bytes, max_withheld: int | None = None) -> LineRelease:
        """Add one frame's bytes and release whatever lines it completed.

        The ceiling is read per call rather than per buffer because it is a
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
        cut = _last_terminator(self._buf, scan_from) + 1
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
