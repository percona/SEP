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

"""Record the scan window of every ``find`` a chunk-to-line splitter runs.

A splitter that carries a newline-free remainder across chunks must search only
the bytes each chunk delivered. A regression back to searching the whole buffer
yields the same lines, so it is invisible to an output comparison and shows up
only in the arguments the search was called with. This recorder makes those
arguments assertable, pinning the narrowing with a test instead of inspection.
"""

from __future__ import annotations

from typing import SupportsIndex, TYPE_CHECKING

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer

__all__ = ["ScanRecordingBytearray"]


class ScanRecordingBytearray(bytearray):
    """Record the start offset and buffer length of every ``find`` run."""

    def __init__(self, *args: object) -> None:
        """Build the buffer and its empty scan log.

        :param args: Any arguments ``bytearray`` itself accepts.
        """
        super().__init__(*args)
        self.scans: list[tuple[int, int]] = []

    def find(
        self,
        sub: ReadableBuffer | SupportsIndex,
        start: SupportsIndex | None = None,
        end: SupportsIndex | None = None,
        /,
    ) -> int:
        """Log the scan window and delegate to ``bytearray.find``.

        :param sub: The byte sequence to search for.
        :param start: The offset the search starts from.
        :param end: The offset the search stops at.
        :return: The index of the first occurrence, or ``-1``.
        """
        self.scans.append((int(start or 0), len(self)))
        return super().find(sub, start, end)
