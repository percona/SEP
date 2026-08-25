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

import pytest

from app.tasks.logs.line_split import (
    LineRelease,
    LineSplit,
    split_complete_lines,
    WithheldLineBuffer,
)


class TestSplitCompleteLines:
    """Test ``split_complete_lines``."""

    def test_empty_buffer(self):
        """Assert an empty buffer yields two empty byte strings."""
        assert split_complete_lines(b"") == LineSplit(b"", b"", forced=False)

    def test_no_terminator_withholds_everything(self):
        """Assert a buffer with no line terminator is withheld whole."""
        assert split_complete_lines(b"card=4111") == LineSplit(
            b"", b"card=4111", forced=False
        )

    def test_single_newline_terminated_line(self):
        """Assert a fully terminated line leaves no remainder."""
        assert split_complete_lines(b"line\n") == LineSplit(
            b"line\n", b"", forced=False
        )

    def test_trailing_partial_after_newline(self):
        """Assert bytes after the last newline are the withheld remainder."""
        assert split_complete_lines(b"done\ncard=41") == LineSplit(
            b"done\n", b"card=41", forced=False
        )

    def test_multiple_lines_split_at_last_terminator(self):
        """Assert the split lands after the last terminator, not the first."""
        assert split_complete_lines(b"a\nb\nc") == LineSplit(
            b"a\nb\n", b"c", forced=False
        )

    def test_carriage_return_is_a_terminator(self):
        """Assert a lone carriage return terminates a line so it flushes."""
        assert split_complete_lines(b"progress\rmore") == LineSplit(
            b"progress\r", b"more", forced=False
        )

    def test_crlf_splits_after_the_newline(self):
        """Assert a carriage-return / newline pair keeps both bytes in complete."""
        assert split_complete_lines(b"a\r\nb") == LineSplit(
            b"a\r\n", b"b", forced=False
        )

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
            b"done\n", b"card=41", forced=False
        )

    def test_remainder_exactly_at_ceiling_still_withheld(self):
        """Assert a remainder equal to the ceiling is still withheld.

        The boundary is strictly greater-than: exactly ``max_withheld`` bytes
        must not force a flush.
        """
        remainder = b"card=41"  # 7 bytes
        assert split_complete_lines(
            b"done\n" + remainder, max_withheld=len(remainder)
        ) == LineSplit(b"done\n", remainder, forced=False)

    def test_remainder_above_ceiling_forces_flush(self):
        """Assert a remainder longer than the ceiling flushes the whole buffer."""
        buf = b"done\ncard=4111"  # remainder is 9 bytes
        assert split_complete_lines(buf, max_withheld=8) == LineSplit(
            buf, b"", forced=True
        )

    def test_no_terminator_above_ceiling_forces_flush(self):
        """Assert an un-terminated buffer longer than the ceiling is flushed whole."""
        buf = b"card=41111111"  # 13 bytes, no terminator
        assert split_complete_lines(buf, max_withheld=8) == LineSplit(
            buf, b"", forced=True
        )

    def test_no_ceiling_never_forces_flush(self):
        """Assert omitting ``max_withheld`` preserves unbounded withholding."""
        buf = b"x" * 100
        assert split_complete_lines(buf) == LineSplit(b"", buf, forced=False)

    def test_forced_flush_preserves_mid_codepoint_bytes(self):
        """Assert a forced flush returns the buffer whole, not a mid-codepoint cut.

        Cutting at ``max_withheld`` could split a multi-byte UTF-8 sequence the
        buffer holds complete; returning ``buf`` intact introduces no such cut,
        though ``buf`` may itself end mid-codepoint as it does here.
        """
        # "é" is two UTF-8 bytes (0xc3 0xa9); an unterminated buffer ending
        # mid-codepoint must still flush as the original bytes.
        buf = b"cafe\xc3"  # incomplete "é"
        split = split_complete_lines(buf, max_withheld=3)
        assert split == LineSplit(buf, b"", forced=True)
        assert split.complete is buf


def _withheld(buf: WithheldLineBuffer) -> bytes:
    """Return the bytes ``buf`` is still withholding.

    Reads private storage: the withheld bytes are deliberately not exposed as a
    public snapshot, and this module is the white-box test of the type that owns
    them.

    :param buf: The buffer to inspect.
    :return: The withheld bytes.
    """
    return bytes(buf._buf)


class _ScanRecordingBytearray(bytearray):
    """Record the start offset of every ``rfind`` run against the buffer."""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)
        self.scan_starts: list[int] = []

    def rfind(self, sub: bytes, start: int = 0, *args: int) -> int:
        """Log the scan start offset and delegate to ``bytearray.rfind``.

        :param sub: The byte sequence to search for.
        :param start: The offset the search starts from.
        :param args: Any trailing ``end`` argument.
        :return: The index of the last occurrence, or ``-1``.
        """
        self.scan_starts.append(start)
        return super().rfind(sub, start, *args)


def _replay_with_full_scans(
    chunks: list[bytes], max_withheld: int | None
) -> tuple[list[tuple[bytes, bool]], bytes]:
    """Replay ``chunks`` through the unnarrowed split as an equivalence oracle.

    Mirrors what the live path did before the buffer type existed: append the
    frame, copy the whole buffer, split it with a full scan, then truncate.

    :param chunks: The frame payloads, in arrival order.
    :param max_withheld: The withheld-bytes ceiling, or ``None`` for unbounded.
    :return: The ``(complete, forced)`` pair each frame released, and the bytes
        left withheld afterwards.
    """
    pending = bytearray()
    releases = []
    for chunk in chunks:
        pending.extend(chunk)
        split = split_complete_lines(bytes(pending), max_withheld=max_withheld)
        del pending[: len(split.complete)]
        releases.append((split.complete, split.forced))
    return releases, bytes(pending)


CHUNK_SEQUENCES = [
    pytest.param([], None, id="no-frames"),
    pytest.param([b""], None, id="empty-frame"),
    pytest.param([b"line\n"], None, id="single-terminated"),
    pytest.param([b"a", b"b", b"c"], None, id="terminator-free-run"),
    pytest.param([b"a", b"b", b"c\n"], None, id="run-then-completion"),
    pytest.param([b"\nlead"], None, id="terminator-at-frame-start"),
    pytest.param([b"a\nb\nc"], None, id="multiple-terminators"),
    pytest.param([b"a\r", b"\nb"], None, id="crlf-split-across-frames"),
    pytest.param([b"tail", b"", b"\n"], None, id="empty-frame-mid-run"),
    pytest.param([b"x" * 4, b"x" * 4], 6, id="run-trips-ceiling"),
    pytest.param([b"done\ncard=4111"], 8, id="terminator-and-over-ceiling"),
    pytest.param([b"done\ncard=41"], 7, id="remainder-exactly-at-ceiling"),
    pytest.param(
        ["café=x\n".encode()[:5], "café=x\n".encode()[5:]], None, id="multibyte-split"
    ),
    pytest.param([b"\n\n\n"], None, id="all-terminators"),
    pytest.param([b"a\r", b"b\r", b"c\r"], None, id="carriage-return-run"),
    pytest.param([b"a\nb"], 0, id="zero-ceiling"),
    pytest.param([b"card=41111111", b"11111111\n"], 8, id="ceiling-splits-a-token"),
]


class TestWithheldLineBuffer:
    """Test ``WithheldLineBuffer``."""

    def test_new_buffer_is_empty(self):
        """Assert a fresh buffer withholds nothing."""
        buf = WithheldLineBuffer()
        assert len(buf) == 0
        assert not buf
        assert _withheld(buf) == b""
        assert buf.drain() == b""

    def test_terminator_free_append_releases_nothing(self):
        """Assert a frame with no terminator releases nothing and is withheld."""
        buf = WithheldLineBuffer()
        assert buf.append(b"card=41") == LineRelease(b"", forced=False)
        assert _withheld(buf) == b"card=41"
        assert buf

    def test_append_releases_up_to_the_last_terminator(self):
        """Assert the release ends at the last terminator, not the first."""
        buf = WithheldLineBuffer()
        assert buf.append(b"a\nb\nc") == LineRelease(b"a\nb\n", forced=False)
        assert _withheld(buf) == b"c"

    def test_accumulated_run_released_whole_by_completion_frame(self):
        """Assert a terminating frame releases everything accumulated before it.

        The narrowed scan must be correct at the moment the buffer is released,
        not only while it grows.
        """
        frame = b"x" * 8
        frames = 4
        buf = WithheldLineBuffer()
        for _ in range(frames):
            assert buf.append(frame) == LineRelease(b"", forced=False)
        assert buf.append(b"end\n") == LineRelease(
            frame * frames + b"end\n", forced=False
        )
        assert not buf

    def test_frame_after_a_partial_release_accumulates_onto_the_remainder(self):
        """Assert a terminator-free frame concatenates onto what was withheld."""
        buf = WithheldLineBuffer()
        buf.append(b"first\ntail")
        assert buf.append(b"more") == LineRelease(b"", forced=False)
        assert _withheld(buf) == b"tailmore"

    def test_terminator_behind_the_scan_start_is_never_re_released(self):
        """Assert a terminator already among the withheld bytes is not re-found.

        Seeds a state ``append`` cannot produce, because the scan window is the
        one thing an all-public exercise of the type cannot observe: with a
        terminator behind the window, a whole-buffer scan releases a line and a
        narrowed scan releases nothing.
        """
        buf = WithheldLineBuffer()
        buf._buf += b"already\nreleased"
        assert buf.append(b"more") == LineRelease(b"", forced=False)
        assert _withheld(buf) == b"already\nreleasedmore"

    def test_carriage_return_is_a_terminator(self):
        """Assert a lone carriage return releases the progress line it ends."""
        buf = WithheldLineBuffer()
        assert buf.append(b"progress\rmore") == LineRelease(b"progress\r", forced=False)
        assert _withheld(buf) == b"more"

    def test_crlf_split_across_frames_releases_both_halves(self):
        """Assert a split carriage-return / newline pair releases at each byte."""
        buf = WithheldLineBuffer()
        assert buf.append(b"a\r") == LineRelease(b"a\r", forced=False)
        assert not buf
        assert buf.append(b"\nb") == LineRelease(b"\n", forced=False)
        assert _withheld(buf) == b"b"

    def test_multibyte_codepoint_split_across_frames_intact(self):
        """Assert a codepoint straddling two frames is released undamaged."""
        raw = "café=x\n".encode()
        buf = WithheldLineBuffer()
        assert buf.append(raw[:4]) == LineRelease(b"", forced=False)
        release = buf.append(raw[4:])
        assert release == LineRelease(raw, forced=False)
        release.complete.decode("utf-8")  # no UnicodeDecodeError

    def test_empty_append_is_a_no_op(self):
        """Assert a frame carrying no bytes changes nothing."""
        buf = WithheldLineBuffer()
        buf.append(b"abc")
        assert buf.append(b"") == LineRelease(b"", forced=False)
        assert _withheld(buf) == b"abc"

    def test_drain_returns_everything_and_clears(self):
        """Assert the end-of-stream drain empties the buffer."""
        buf = WithheldLineBuffer()
        buf.append(b"tail")
        assert buf.drain() == b"tail"
        assert not buf
        assert buf.drain() == b""

    def test_release_is_a_copy_not_a_view(self):
        """Assert a released value does not change when the next frame arrives.

        A view into the live buffer would let a caller observe bytes mutating
        under it — including bytes it already anonymized and pushed.
        """
        buf = WithheldLineBuffer()
        release = buf.append(b"line\ntail")
        assert isinstance(release.complete, bytes)
        buf.append(b"more\n")
        assert release.complete == b"line\n"

    def test_withheld_bytes_have_no_non_destructive_snapshot(self):
        """Assert the withheld bytes have no non-destructive snapshot.

        The type exists so no caller pays for the whole buffer on every frame.
        A snapshot that leaves the buffer intact hands that cost straight back.
        """
        buf = WithheldLineBuffer()
        buf.append(b"tail")
        with pytest.raises(TypeError):
            bytes(buf)

    def test_remainder_exactly_at_ceiling_still_withheld(self):
        """Assert the ceiling boundary is strictly greater-than."""
        buf = WithheldLineBuffer()
        assert buf.append(b"done\ncard=41", max_withheld=7) == LineRelease(
            b"done\n", forced=False
        )
        assert _withheld(buf) == b"card=41"

    def test_remainder_above_ceiling_forces_flush(self):
        """Assert an over-ceiling remainder flushes the whole buffer and clears it."""
        buf = WithheldLineBuffer()
        assert buf.append(b"done\ncard=4111", max_withheld=8) == LineRelease(
            b"done\ncard=4111", forced=True
        )
        assert not buf

    def test_terminator_free_run_trips_ceiling_across_frames(self):
        """Assert the ceiling measures the whole withheld buffer, not one frame."""
        buf = WithheldLineBuffer()
        assert buf.append(b"x" * 4, max_withheld=6) == LineRelease(b"", forced=False)
        assert buf.append(b"y" * 4, max_withheld=6) == LineRelease(
            b"x" * 4 + b"y" * 4, forced=True
        )
        assert not buf

    def test_no_ceiling_never_forces_flush(self):
        """Assert an unset ceiling preserves unbounded withholding."""
        frame = b"x" * 100
        frames = 10
        buf = WithheldLineBuffer()
        for _ in range(frames):
            assert buf.append(frame) == LineRelease(b"", forced=False)
        assert len(buf) == frames * len(frame)

    def test_lowered_ceiling_forces_flush_on_the_next_frame(self):
        """Assert a runtime-lowered ceiling applies to the already-withheld bytes.

        The ceiling is a hot-tunable setting read per frame, so an operator
        lowering it must unblock a buffer that is already over the new value.
        """
        buf = WithheldLineBuffer()
        buf.append(b"x" * 10, max_withheld=100)
        assert buf.append(b"", max_withheld=5) == LineRelease(b"x" * 10, forced=True)
        assert not buf

    def test_forced_flush_preserves_mid_codepoint_bytes(self):
        """Assert a forced flush releases the withheld bytes uncut.

        Cutting at the ceiling could split a multi-byte UTF-8 sequence the
        buffer holds complete; releasing everything introduces no such cut.
        """
        buf = WithheldLineBuffer()
        raw = b"cafe\xc3"  # incomplete "é"
        assert buf.append(raw, max_withheld=3) == LineRelease(raw, forced=True)
        assert not buf

    def test_ceiling_releases_a_token_in_halves(self):
        """Assert the ceiling splits an un-terminated token across two releases.

        This is the accepted redaction-boundary leak: each half is anonymized
        alone, so a token straddling the flush is matched in neither. Pinned so
        the boundary cannot move unnoticed.
        """
        buf = WithheldLineBuffer()
        assert buf.append(b"card=41111111", max_withheld=8) == LineRelease(
            b"card=41111111", forced=True
        )
        assert buf.append(b"11111111\n") == LineRelease(b"11111111\n", forced=False)

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            pytest.param(b"a\nb", LineRelease(b"a\nb", forced=True), id="tail-remains"),
            pytest.param(b"a\n", LineRelease(b"a\n", forced=False), id="nothing-left"),
        ],
    )
    def test_zero_ceiling_forces_a_flush_only_when_a_tail_remains(self, data, expected):
        """Assert a zero ceiling withholds nothing yet only forces on a remainder.

        A zero ceiling is falsy, so a truthiness test in its place would stop
        forcing the flush a strictly-greater-than comparison still forces.
        """
        buf = WithheldLineBuffer()
        assert buf.append(data, max_withheld=0) == expected
        assert not buf

    @pytest.mark.parametrize(("chunks", "max_withheld"), CHUNK_SEQUENCES)
    def test_matches_the_unnarrowed_full_scan(self, chunks, max_withheld):
        """Assert the narrowed scan releases exactly what a full scan releases."""
        buf = WithheldLineBuffer()
        releases = [
            tuple(buf.append(chunk, max_withheld=max_withheld)) for chunk in chunks
        ]
        expected_releases, expected_remainder = _replay_with_full_scans(
            chunks, max_withheld
        )
        assert releases == expected_releases
        assert _withheld(buf) == expected_remainder

    @pytest.mark.parametrize(("chunks", "max_withheld"), CHUNK_SEQUENCES)
    def test_withheld_bytes_stay_terminator_free(self, chunks, max_withheld):
        """Assert no frame ever leaves a terminator withheld.

        The narrowed scan is only exact while this holds: a terminator left
        behind would silently withhold a line that was already complete.
        """
        buf = WithheldLineBuffer()
        for chunk in chunks:
            buf.append(chunk, max_withheld=max_withheld)
            withheld = _withheld(buf)
            assert b"\n" not in withheld
            assert b"\r" not in withheld

    def test_each_frame_scans_only_the_bytes_it_delivered(self):
        """Assert no frame's scan reaches back into bytes it did not deliver.

        A full-buffer scan is behaviourally indistinguishable while the buffer
        obeys its own invariant, so the narrowing is pinned directly or a
        regression to quadratic work over a growing buffer goes unnoticed.
        """
        buf = WithheldLineBuffer()
        recorder = _ScanRecordingBytearray()
        buf._buf = recorder

        for frame in (b"a" * 10, b"b" * 5, b"c" * 3):
            scan_from = len(buf)
            recorder.scan_starts.clear()
            buf.append(frame)
            assert recorder.scan_starts, "append performed no scan"
            assert set(recorder.scan_starts) == {scan_from}
