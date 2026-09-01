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

"""Define tests for RemoteAPI request-logging helpers and the upload primitive."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import patch

import pytest
from aioresponses import aioresponses
from fastapi import HTTPException, status

from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPConflictException,
    HTTPNotFoundException,
)
from app.core.requests import RemoteAPI
from app.core.requests.remote_api import (
    _iter_lines_from_chunks,
    _REDACTED_VALUE,
    _sanitize_request_kwargs,
    as_json_array,
    as_json_object,
    UPSTREAM_NON_JSON_HEADER,
)
from app.core.requests.remote_api import (
    _MAX_STREAM_LINE_BYTES as _REAL_CAP,
)
from tests.app.scan_recording import ScanRecordingBytearray

_UPLOAD_URL = "http://localhost:8000/upload"


@pytest.fixture
def remote_api() -> RemoteAPI:
    """Provide a real RemoteAPI client pointed at a local base URL."""
    return RemoteAPI(endpoint="http://localhost:8000/")


def _one_file() -> dict:
    """Return a single-file multipart mapping for upload tests."""
    return {"file": ("bundle.tar.gz", b"bundle-bytes", "application/octet-stream")}


def test_redacts_sensitive_headers():
    """Verify credential-bearing headers are masked, others preserved."""
    safe = _sanitize_request_kwargs(
        {"headers": {"Authorization": "Bearer x", "Accept": "application/json"}}
    )

    assert safe["headers"]["Authorization"] == _REDACTED_VALUE
    assert safe["headers"]["Accept"] == "application/json"


def test_redacts_password_in_json_body():
    """Verify a password in a JSON body is masked in the logged copy."""
    safe = _sanitize_request_kwargs({"json": {"user": "alice", "password": "secret"}})

    assert safe["json"]["password"] == _REDACTED_VALUE
    assert safe["json"]["user"] == "alice"


def test_redacts_password_in_form_data_body():
    """Verify a password in a form ``data`` body is masked in the logged copy."""
    safe = _sanitize_request_kwargs(
        {"data": {"grant_type": "password", "password": "secret"}}
    )

    assert safe["data"]["password"] == _REDACTED_VALUE
    assert safe["data"]["grant_type"] == "password"


def test_does_not_mutate_the_original_kwargs():
    """Verify the outgoing request keeps its real credentials (copy is masked)."""
    kwargs = {
        "headers": {"Authorization": "Bearer x"},
        "json": {"password": "secret"},
    }

    _sanitize_request_kwargs(kwargs)

    assert kwargs["headers"]["Authorization"] == "Bearer x"
    assert kwargs["json"]["password"] == "secret"


def test_passes_through_non_dict_body():
    """Verify a non-mapping body is left untouched."""
    safe = _sanitize_request_kwargs({"data": b"raw-bytes"})

    assert safe["data"] == b"raw-bytes"


def test_extra_sensitive_headers_masked():
    """Mask a caller-supplied custom header name via the extra-redaction keyword."""
    safe = _sanitize_request_kwargs(
        {"headers": {"X-Custom-Token": "raw-secret", "Accept": "application/json"}},
        extra_sensitive_headers=frozenset({"x-custom-token"}),
    )

    assert safe["headers"]["X-Custom-Token"] == _REDACTED_VALUE
    assert safe["headers"]["Accept"] == "application/json"


def test_extra_sensitive_headers_defaults_to_existing_behavior():
    """Keep a custom header untouched when no extra redaction is requested."""
    safe = _sanitize_request_kwargs({"headers": {"X-Custom-Token": "raw-secret"}})

    assert safe["headers"]["X-Custom-Token"] == "raw-secret"


def test_extra_sensitive_body_fields_masked():
    """Mask a caller-supplied custom body key via the extra-redaction keyword."""
    safe = _sanitize_request_kwargs(
        {"json": {"client_token": "raw-secret", "ticket_number": "CS0001"}},
        extra_sensitive_body_fields=frozenset({"client_token"}),
    )

    assert safe["json"]["client_token"] == _REDACTED_VALUE
    assert safe["json"]["ticket_number"] == "CS0001"


def test_extra_sensitive_body_fields_defaults_to_existing_behavior():
    """Keep a custom body key untouched when no extra redaction is requested."""
    safe = _sanitize_request_kwargs({"json": {"client_token": "raw-secret"}})

    assert safe["json"]["client_token"] == "raw-secret"


def test_extra_sensitive_body_fields_keeps_built_in_masking():
    """Mask the always-sensitive body keys alongside the caller-supplied ones."""
    safe = _sanitize_request_kwargs(
        {"json": {"password": "pw", "client_token": "raw-secret"}},
        extra_sensitive_body_fields=frozenset({"client_token"}),
    )

    assert safe["json"]["password"] == _REDACTED_VALUE
    assert safe["json"]["client_token"] == _REDACTED_VALUE


def test_redact_headers_masks_within_context_only(remote_api):
    """Mask extra header names only for the duration of the ``redact_headers`` block."""
    with remote_api.redact_headers(["X-Custom-Token"]):
        active = remote_api._extra_sensitive_headers.get()
    after = remote_api._extra_sensitive_headers.get()

    assert active == frozenset({"x-custom-token"})
    assert after == frozenset()


def test_redact_headers_nesting_unions_with_outer_context(remote_api):
    """Accumulate an inner ``redact_headers`` block's names on top of the outer set."""
    with remote_api.redact_headers(["X-Outer"]):
        with remote_api.redact_headers(["X-Inner"]):
            nested = remote_api._extra_sensitive_headers.get()
        restored = remote_api._extra_sensitive_headers.get()

    assert nested == frozenset({"x-outer", "x-inner"})
    assert restored == frozenset({"x-outer"})


def test_redact_body_fields_masks_within_context_only(remote_api):
    """Mask extra body keys only for the duration of the ``redact_body_fields`` block."""
    with remote_api.redact_body_fields(["Client_Token"]):
        active = remote_api._extra_sensitive_body_fields.get()
    after = remote_api._extra_sensitive_body_fields.get()

    assert active == frozenset({"client_token"})
    assert after == frozenset()


def test_redact_body_fields_nesting_unions_with_outer_context(remote_api):
    """Accumulate an inner ``redact_body_fields`` block's keys on top of the outer set."""
    with remote_api.redact_body_fields(["outer_token"]):
        with remote_api.redact_body_fields(["inner_token"]):
            nested = remote_api._extra_sensitive_body_fields.get()
        restored = remote_api._extra_sensitive_body_fields.get()

    assert nested == frozenset({"outer_token", "inner_token"})
    assert restored == frozenset({"outer_token"})


class TestUpload:
    """Cover the multipart ``RemoteAPI.upload`` primitive."""

    pytestmark = pytest.mark.asyncio

    async def test_returns_parsed_json_body(self, remote_api):
        """Return the parsed JSON body on a 2xx JSON response."""
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_200_OK, payload={"ok": True})
            async with remote_api:
                result = await remote_api.upload(
                    "upload", files=_one_file(), fields={"client_id": "acme"}
                )

        assert result == {"ok": True}

    async def test_sends_multipart_content_type_with_boundary(self, remote_api):
        """Send a ``multipart/form-data`` Content-Type carrying a boundary, not JSON."""
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_200_OK, payload={"ok": True})
            async with remote_api:
                await remote_api.upload(
                    "upload", files=_one_file(), fields={"client_id": "acme"}
                )
            request = next(iter(mock.requests.values()))[0]

        content_type = request.kwargs["headers"]["Content-Type"]
        assert content_type.startswith("multipart/form-data")
        assert "boundary=" in content_type

    async def test_maps_conflict_to_project_exception(self, remote_api):
        """Map a 409 response to ``HTTPConflictException`` via ``request``."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_409_CONFLICT,
                payload={"detail": "already ingested"},
            )
            async with remote_api:
                with pytest.raises(HTTPConflictException):
                    await remote_api.upload("upload", files=_one_file())

    async def test_maps_bad_gateway_to_project_exception(self, remote_api):
        """Map a 502 response to ``HTTPBadGatewayException`` via ``request``."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_502_BAD_GATEWAY,
                payload={"detail": "upstream down"},
            )
            async with remote_api:
                with pytest.raises(HTTPBadGatewayException):
                    await remote_api.upload("upload", files=_one_file())

    async def test_carries_upstream_not_found_detail(self, remote_api):
        """Carry an upstream 404's body ``detail`` onto ``HTTPNotFoundException``.

        Sub-app routes discriminate two 404 conditions by ``detail`` alone, so a
        proxy route can only relay that distinction if the upstream string survives
        the mapping rather than collapsing to the exception's default.
        """
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_404_NOT_FOUND,
                payload={
                    "detail": "System observation not collected yet for this node"
                },
            )
            async with remote_api:
                with pytest.raises(HTTPNotFoundException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert (
            exc_info.value.detail
            == "System observation not collected yet for this node"
        )

    async def test_non_json_not_found_stays_unmapped(self, remote_api):
        """Leave a non-JSON 404 as a bare ``HTTPException``.

        A 404 with a non-JSON body comes from proxy or gateway infrastructure, not
        from an app route answering "this resource is absent". Mapping it would let
        a caller narrowing to ``HTTPNotFoundException`` to read an uncollected
        observation treat an infrastructure failure as a real absence.
        """
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_404_NOT_FOUND,
                body="<html>404 not found</html>",
                content_type="text/html",
            )
            async with remote_api:
                with pytest.raises(HTTPException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert not isinstance(exc_info.value, HTTPNotFoundException)
        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert exc_info.value.headers.get(UPSTREAM_NON_JSON_HEADER) == "1"

    async def test_not_found_without_detail_key_falls_back(self, remote_api):
        """Fall back to the generic detail for a JSON 404 carrying no ``detail``.

        Routes that discriminate 404 conditions by ``detail`` must not read the
        fallback as one of their own strings, so pin what a detail-less upstream
        body produces.
        """
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_404_NOT_FOUND,
                payload={"message": "gone"},
            )
            async with remote_api:
                with pytest.raises(HTTPNotFoundException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert exc_info.value.detail == "An unexpected error occurred on the server."

    async def test_non_json_success_body_returns_none(self, remote_api):
        """Return ``None`` for a 2xx response whose body is not JSON."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_201_CREATED,
                body="OK",
                content_type="text/plain",
            )
            async with remote_api:
                result = await remote_api.upload("upload", files=_one_file())

        assert result is None

    async def test_non_json_error_body_still_raises_stamped(self, remote_api):
        """Raise the stamped upstream error for a non-JSON 4xx/5xx body."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_502_BAD_GATEWAY,
                body="<html>bad gateway</html>",
                content_type="text/html",
            )
            async with remote_api:
                with pytest.raises(HTTPException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
        assert exc_info.value.headers.get(UPSTREAM_NON_JSON_HEADER) == "1"

    async def test_error_status_with_non_dict_json_body(self, remote_api):
        """Map an error status whose JSON body is a list, not an object."""
        with aioresponses() as mock:
            mock.post(
                _UPLOAD_URL,
                status=status.HTTP_502_BAD_GATEWAY,
                payload=[{"loc": "body", "msg": "invalid"}],
            )
            async with remote_api:
                with pytest.raises(HTTPBadGatewayException) as exc_info:
                    await remote_api.upload("upload", files=_one_file())

        assert exc_info.value.detail == "An unexpected error occurred on the server."


class TestDrainOnRebind:
    """Cover the in-flight accounting behind ``hold`` and ``close_when_idle``."""

    pytestmark = pytest.mark.asyncio

    async def test_idle_client_closes_immediately(self, remote_api):
        """Close synchronously when no consumer holds the client."""
        await remote_api.open()

        await remote_api.close_when_idle()

        assert remote_api._session is None

    async def test_active_hold_defers_the_close(self, remote_api):
        """Keep the session open until the holder releases it."""
        await remote_api.open()

        async with remote_api.hold():
            await remote_api.close_when_idle()
            assert remote_api._session is not None

        assert remote_api._session is None

    async def test_nested_holds_close_once_at_zero(self, remote_api):
        """Close on the outermost release, not on an inner one."""
        await remote_api.open()

        async with remote_api.hold():
            async with remote_api.hold():
                await remote_api.close_when_idle()
            assert remote_api._session is not None

        assert remote_api._session is None

    async def test_request_takes_its_own_hold(self, remote_api):
        """Keep the session open when a rebind lands mid-call with no outer hold."""
        with aioresponses() as mock:
            mock.post(_UPLOAD_URL, status=status.HTTP_200_OK, payload={"ok": True})
            await remote_api.open()
            async with remote_api._request("POST", "upload"):
                await remote_api.close_when_idle()
                assert remote_api._session is not None

        assert remote_api._session is None

    async def test_release_on_exception_still_closes(self, remote_api):
        """Perform the deferred close even when the held block raises."""
        await remote_api.open()

        async def consumer() -> None:
            async with remote_api.hold():
                await remote_api.close_when_idle()
                raise RuntimeError("consumer blew up")

        with pytest.raises(RuntimeError, match="consumer blew up"):
            await consumer()

        assert remote_api._session is None

    async def test_release_on_cancellation_still_closes(self, remote_api):
        """Perform the deferred close when the consuming task is cancelled."""
        await remote_api.open()
        held = asyncio.Event()

        async def consumer() -> None:
            async with remote_api.hold():
                held.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(consumer())
        await asyncio.wait_for(held.wait(), timeout=5)
        await remote_api.close_when_idle()
        assert remote_api._session is not None

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert remote_api._session is None

    async def test_hold_alone_never_closes(self, remote_api):
        """Leave the session open when no rebind asked for a close."""
        await remote_api.open()

        async with remote_api.hold():
            pass

        assert remote_api._session is not None
        await remote_api.close()

    async def test_repeated_close_when_idle_closes_once(self, remote_api):
        """Treat a second rebind before the first drains as a no-op."""
        await remote_api.open()

        async with remote_api.hold():
            await remote_api.close_when_idle()
            await remote_api.close_when_idle()
            assert remote_api._session is not None

        assert remote_api._session is None

    async def test_flag_is_cleared_after_the_deferred_close(self, remote_api):
        """Leave a reopened client unaffected by the drain that already fired."""
        await remote_api.open()
        async with remote_api.hold():
            await remote_api.close_when_idle()

        await remote_api.open()
        async with remote_api.hold():
            pass

        assert remote_api._session is not None
        await remote_api.close()

    async def test_close_still_closes_unconditionally(self, remote_api):
        """Keep ``close`` immediate so ``close_all`` and shutdown are unchanged."""
        await remote_api.open()

        async with remote_api.hold():
            await remote_api.close()
            assert remote_api._session is None


async def _achunks(chunks: list[bytes]) -> AsyncGenerator[bytes, None]:
    """Yield each chunk from ``chunks`` as an async iterator.

    :param chunks: The chunk payloads, in arrival order.
    :yield: Each chunk unchanged.
    """
    for chunk in chunks:
        yield chunk


def _replay_with_full_scans(
    chunks: list[bytes], cap: int
) -> tuple[list[bytes], int | None, bytes]:
    """Replay ``chunks`` through the unnarrowed loop as an equivalence oracle.

    Mirrors what ``_iter_lines_from_chunks`` did before the search was narrowed:
    one cursor, restarting the search at ``0`` on every chunk.

    :param chunks: The chunk payloads, in arrival order.
    :param cap: The per-line byte cap to enforce.
    :return: The lines yielded, the size reported by the cap violation that
        stopped the replay (``None`` when none did), and the bytes still
        buffered when the replay ended.
    """
    lines: list[bytes] = []
    buffer = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        buffer.extend(chunk)
        offset = 0
        while True:
            newline_pos = buffer.find(b"\n", offset)
            if newline_pos == -1:
                break
            line_end = newline_pos + 1
            line_size = line_end - offset
            if line_size > cap:
                return lines, line_size, bytes(buffer)
            lines.append(bytes(buffer[offset:line_end]))
            offset = line_end
        if offset:
            del buffer[:offset]
        if len(buffer) > cap:
            return lines, len(buffer), bytes(buffer)
    if buffer:
        if len(buffer) > cap:
            return lines, len(buffer), bytes(buffer)
        lines.append(bytes(buffer))
    return lines, None, bytes(buffer)


@pytest.fixture
def recorded_buffers(monkeypatch: pytest.MonkeyPatch) -> list[ScanRecordingBytearray]:
    """Make ``_iter_lines_from_chunks`` build scan-recording buffers.

    The function owns its buffer and takes no injection point, so the module
    global shadows the builtin for the duration of the test.

    :param monkeypatch: The pytest monkeypatch fixture.
    :return: The list the factory appends each buffer it builds to.
    """
    created: list[ScanRecordingBytearray] = []

    def factory(*args: object) -> ScanRecordingBytearray:
        buffer = ScanRecordingBytearray(*args)
        created.append(buffer)
        return buffer

    monkeypatch.setattr(
        "app.core.requests.remote_api.bytearray", factory, raising=False
    )
    return created


CHUNK_SEQUENCES = [
    pytest.param([], id="no-chunks"),
    pytest.param([b""], id="empty-chunk"),
    pytest.param([b"", b"", b""], id="only-empty-chunks"),
    pytest.param([b"line\n"], id="single-terminated"),
    pytest.param([b"no-newline"], id="single-unterminated"),
    pytest.param([b"a", b"b", b"c"], id="newline-free-run"),
    pytest.param([b"x" * 16] * 8 + [b"end\n"], id="long-run-then-completion"),
    pytest.param([b"one-", b"line-", b"split\nnext\n"], id="straddles-three-chunks"),
    pytest.param([b"tail", b"\nlead"], id="newline-is-first-arriving-byte"),
    pytest.param([b"a\nb\nc\n"], id="multiple-terminators-one-chunk"),
    pytest.param([b"\n\n\n"], id="only-terminators"),
    pytest.param([b"x\n", b"\n"], id="empty-line-in-its-own-chunk"),
    pytest.param([b"a\r", b"\nb"], id="carriage-return-is-not-a-terminator"),
    pytest.param([b"tail", b"", b"\n"], id="empty-chunk-mid-run"),
    pytest.param(
        ["café=x\n".encode()[:5], "café=x\n".encode()[5:]], id="multibyte-split"
    ),
]

CAP_BOUNDARIES = [
    pytest.param([b"x" * 8], 8, id="remainder-exactly-at-cap"),
    pytest.param([b"x" * 9], 8, id="remainder-over-cap"),
    pytest.param([b"x" * 7 + b"\n"], 8, id="line-exactly-at-cap"),
    pytest.param([b"x" * 8 + b"\n"], 8, id="line-over-cap"),
    pytest.param([b"x" * 4, b"x" * 4], 8, id="remainder-reaches-cap-across-chunks"),
    pytest.param([b"x" * 5, b"x" * 5], 8, id="remainder-passes-cap-across-chunks"),
    pytest.param([b"x" * 4, b"x" * 4 + b"\n"], 8, id="line-over-cap-across-chunks"),
]


class TestIterLinesFromChunks:
    """Test the narrowed newline search in ``_iter_lines_from_chunks``."""

    @staticmethod
    async def _collect(
        chunks: list[bytes], cap: int
    ) -> tuple[list[bytes], ValueError | None]:
        """Run ``chunks`` through ``_iter_lines_from_chunks`` under ``cap``.

        :param chunks: The chunk payloads, in arrival order.
        :param cap: The per-line byte cap to patch in for the run.
        :return: The lines yielded, and the ``ValueError`` that stopped the run
            (``None`` when none did).
        """
        lines: list[bytes] = []
        with patch("app.core.requests.remote_api._MAX_STREAM_LINE_BYTES", cap):
            try:
                async for line in _iter_lines_from_chunks(_achunks(chunks), "/p/"):
                    # A comprehension would discard the lines yielded before the
                    # cap raised, which is half of what these tests compare.
                    lines.append(line)  # noqa: PERF401
            except ValueError as exc:
                return lines, exc
        return lines, None

    async def _assert_matches_the_oracle(
        self,
        chunks: list[bytes],
        cap: int,
        buffers: list[ScanRecordingBytearray],
    ) -> None:
        """Assert a narrowed run is indistinguishable from an unnarrowed one.

        The remainder is compared through the recorded buffer because the
        generator owns it: on a cap violation it never reaches the end-of-stream
        flush, so the bytes left behind are otherwise unobservable.

        :param chunks: The chunk payloads, in arrival order.
        :param cap: The per-line byte cap to enforce on both runs.
        :param buffers: The buffers the narrowed run built.
        """
        expected_lines, expected_size, expected_buffer = _replay_with_full_scans(
            chunks, cap
        )
        lines, exc = await self._collect(chunks, cap)

        assert lines == expected_lines
        assert bytes(buffers[0]) == expected_buffer
        if expected_size is None:
            assert exc is None
        else:
            assert f"size={expected_size}, path=/p/" in str(exc)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chunks", CHUNK_SEQUENCES)
    @pytest.mark.parametrize("cap", [8, 64, _REAL_CAP], ids=["tiny", "small", "real"])
    async def test_matches_the_unnarrowed_loop(
        self,
        chunks: list[bytes],
        cap: int,
        recorded_buffers: list[ScanRecordingBytearray],
    ) -> None:
        """Assert the narrowed search yields what a search from zero yields."""
        await self._assert_matches_the_oracle(chunks, cap, recorded_buffers)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("chunks", "cap"), CAP_BOUNDARIES)
    async def test_cap_boundary_matches_the_unnarrowed_loop(
        self,
        chunks: list[bytes],
        cap: int,
        recorded_buffers: list[ScanRecordingBytearray],
    ) -> None:
        """Assert the cap fires on the same inputs, naming the same size."""
        await self._assert_matches_the_oracle(chunks, cap, recorded_buffers)

    @pytest.mark.asyncio
    async def test_straddling_line_keeps_the_carried_remainder(self) -> None:
        """Assert the first line a chunk completes still carries earlier bytes.

        Collapsing the search cursor into the line-start cursor drops the
        remainder from this line and hands a truncated line to the consumer.
        """
        lines, exc = await self._collect([b"head-", b"tail\n"], 64)

        assert lines == [b"head-tail\n"]
        assert exc is None

    @pytest.mark.asyncio
    async def test_cap_measures_the_whole_line_not_the_arriving_chunk(self) -> None:
        """Assert an oversized line built from several chunks still raises.

        Measuring the line from the search cursor would report only the arriving
        chunk's share, letting an over-cap line through.
        """
        lines, exc = await self._collect([b"x" * 700, b"y" * 700 + b"\n"], 1024)

        assert lines == []
        assert "size=1401, path=/p/" in str(exc)

    @pytest.mark.asyncio
    async def test_scan_starts_at_the_pre_append_length(
        self, recorded_buffers: list[ScanRecordingBytearray]
    ) -> None:
        """Assert each chunk's search begins where the previous one stopped."""
        lines, _ = await self._collect([b"x" * 4] * 4, 64)

        assert lines == [b"x" * 16]
        assert [start for start, _ in recorded_buffers[0].scans] == [0, 4, 8, 12]

    @pytest.mark.asyncio
    async def test_total_scan_work_is_linear_in_the_delivered_bytes(
        self, recorded_buffers: list[ScanRecordingBytearray]
    ) -> None:
        """Assert a newline-free run never re-examines the carried remainder."""
        chunks = [b"x" * 32] * 16 + [b"end\n"]
        await self._collect(chunks, _REAL_CAP)

        scanned = sum(end - start for start, end in recorded_buffers[0].scans)
        assert scanned == sum(map(len, chunks))

    @pytest.mark.asyncio
    async def test_releasing_chunk_still_scans_only_its_own_bytes(
        self, recorded_buffers: list[ScanRecordingBytearray]
    ) -> None:
        """Assert the chunk that yields the buffer narrows its search too.

        Work proportional to the buffer is legitimate on the chunk that hands
        those bytes to the consumer; the search for the terminator is not.
        """
        lines, _ = await self._collect([b"x" * 64, b"end\n"], _REAL_CAP)

        assert lines == [b"x" * 64 + b"end\n"]
        assert recorded_buffers[0].scans[-2:] == [(64, 68), (68, 68)]


class TestJSONShapeNarrowing:
    """Cover the helpers that narrow a verb method's JSON return union."""

    def test_object_passes_a_mapping_through(self) -> None:
        """Assert a JSON object is returned as a plain dict."""
        assert as_json_object({"a": 1}) == {"a": 1}

    def test_object_accepts_an_empty_mapping(self) -> None:
        """Assert an empty object is a valid payload, not a fault."""
        assert as_json_object({}) == {}

    def test_object_rejects_an_array(self) -> None:
        """Assert a JSON array is reported as an upstream fault."""
        with pytest.raises(HTTPBadGatewayException) as exc_info:
            as_json_object([{"a": 1}])

        assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    def test_object_rejects_no_content(self) -> None:
        """Assert HTTP 204's ``None`` is reported rather than returned."""
        with pytest.raises(HTTPBadGatewayException) as exc_info:
            as_json_object(None)

        assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    def test_array_passes_a_list_of_objects_through(self) -> None:
        """Assert a JSON array of objects is returned unchanged."""
        assert as_json_array([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

    def test_array_accepts_an_empty_list(self) -> None:
        """Assert an empty array is a valid payload, not a fault."""
        assert as_json_array([]) == []

    def test_array_rejects_non_object_elements(self) -> None:
        """Assert the declared ``list[dict]`` is checked, not merely asserted."""
        with pytest.raises(HTTPBadGatewayException) as exc_info:
            as_json_array([1, 2])

        assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    def test_array_rejects_an_object(self) -> None:
        """Assert a JSON object is reported as an upstream fault."""
        with pytest.raises(HTTPBadGatewayException):
            as_json_array({"a": 1})

    def test_array_rejects_no_content(self) -> None:
        """Assert HTTP 204's ``None`` is reported rather than returned."""
        with pytest.raises(HTTPBadGatewayException):
            as_json_array(None)
