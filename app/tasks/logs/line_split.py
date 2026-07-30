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
"""

# ``\n`` and ``\r``. A carriage return is treated as a terminator so that
# ``\r``-driven progress output does not stall un-flushed on the live tail.
# Both are ASCII (< 0x80), so they can never appear inside a multi-byte UTF-8
# sequence -- splitting on either is inherently codepoint-safe.
_LINE_TERMINATORS = (0x0A, 0x0D)


def split_complete_lines(buf: bytes) -> tuple[bytes, bytes]:
    r"""Split ``buf`` at the last line terminator.

    :param buf: The raw (pre-anonymization) bytes fetched so far.
    :return: ``(complete, remainder)`` where ``complete`` is every byte up to
        and including the last ``\n`` or ``\r`` and ``remainder`` is the
        trailing partial line to withhold. When ``buf`` holds no terminator the
        whole buffer is withheld as the remainder.
    """
    for index in range(len(buf) - 1, -1, -1):
        if buf[index] in _LINE_TERMINATORS:
            return buf[: index + 1], buf[index + 1 :]
    return b"", buf
