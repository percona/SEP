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

"""Define tests for ``app.tasks.logs.log_reader``."""

import base64
import gzip
import json
import logging

import pytest
from sqlalchemy.orm import undefer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryManager
from app.tasks.logs.log_reader import (
    byte_offset_for_last_n_lines,
    decompress_legacy_logs,
    has_legacy_logs,
    iter_task_history_logs,
)
from app.tasks.logs.log_writer import TaskHistoryLogWriter
from app.tasks.models import TaskHistory, TaskLogType

EXPECTED_UTF8_TRIM_START = 4


async def _collect(agen):
    """Materialize an async generator into a list."""
    return [item async for item in agen]


async def _reload(session: AsyncSession, history: TaskHistory) -> TaskHistory:
    """Reload ``history`` with ``execution_request`` undeferred."""
    return await TaskHistoryManager.get_or_404(
        session,
        query_options=[undefer(TaskHistory.execution_request)],
        id=history.id,
    )


@pytest.mark.asyncio
async def test_iter_task_history_logs_reads_chunks(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the chunk path yields chunk rows in order."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk-one",
        force_flush=True,
        producer_offset_after=9,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"chunk-two",
        force_flush=True,
        producer_offset_after=18,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history))
    assert [log.msg for log in logs] == ["chunk-one", "chunk-two"]
    assert [log.type for log in logs] == [TaskLogType.STDOUT, TaskLogType.STDOUT]


@pytest.mark.asyncio
async def test_iter_task_history_logs_source_filter(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``source`` filters the chunk stream."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"run-out",
        force_flush=True,
        producer_offset_after=7,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="prepare",
        stream=TaskLogType.STDOUT,
        new_bytes=b"prep-out",
        force_flush=True,
        producer_offset_after=8,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, source="run-script"))
    assert [log.step for log in logs] == ["run-script"]
    assert [log.msg for log in logs] == ["run-out"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_start_offset_trims_chunk(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the first partial chunk is trimmed to start at the offset."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"abcdefgh",
        force_flush=True,
        producer_offset_after=8,
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={"run-script": {TaskLogType.STDOUT: 3}},
        )
    )
    assert [log.msg for log in logs] == ["defgh"]
    assert [log.offset for log in logs] == [8]


@pytest.mark.asyncio
async def test_iter_task_history_logs_start_offset_skips_fully_covered(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert chunks entirely below the start offset are skipped."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"first",
        force_flush=True,
        producer_offset_after=5,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"second",
        force_flush=True,
        producer_offset_after=11,
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={"run-script": {TaskLogType.STDOUT: 5}},
        )
    )
    assert [log.msg for log in logs] == ["second"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_falls_back_to_legacy_blob(
    session: AsyncSession,
    created_task_with_history: TaskHistory,
):
    """Assert the legacy blob is read when no chunks exist and a warning fires."""
    history = created_task_with_history
    legacy = {
        "run-script": {
            TaskLogType.STDOUT.value: "legacy stdout",
            TaskLogType.STDERR.value: "legacy stderr",
        }
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(legacy).encode())).decode()
    history.execution_request.tracking["task_logs"] = encoded
    saved = await TaskHistoryManager.save(
        session, history, flag_modified_fields=["execution_request"]
    )

    history = await _reload(session, saved)
    reader_logger = logging.getLogger("app.tasks.logs.log_reader")
    captured = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    handler = _Capture(level=logging.WARNING)
    reader_logger.addHandler(handler)
    try:
        logs = await _collect(iter_task_history_logs(session, history))
    finally:
        reader_logger.removeHandler(handler)

    warnings = [
        record
        for record in captured
        if record.getMessage() == "taskhistory_log dual-read fallback used"
    ]
    assert warnings
    assert warnings[0].event == "taskhistory_log_fallback"
    assert warnings[0].task_history_id == history.id
    messages = [log.msg for log in logs]
    assert "legacy stdout" in messages
    assert "legacy stderr" in messages


@pytest.mark.asyncio
async def test_iter_task_history_logs_empty_history_yields_nothing(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert an empty history without legacy content yields nothing."""
    history = created_task_with_history
    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history))
    assert logs == []


@pytest.mark.asyncio
async def test_iter_task_history_logs_start_offset_trims_multibyte_chunk(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the trim path uses a byte offset even for non-ASCII content.

    Regression test for SEP-817: the reader used ``chunk.content[trim:]``
    which is a code-point slice on a ``str``, so a byte-offset resume
    position would land in the wrong place for multi-byte characters.
    """
    history = created_task_with_history
    payload = "\u00e9\u00e9\u00e9tail".encode()
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={
                "run-script": {TaskLogType.STDOUT: EXPECTED_UTF8_TRIM_START}
            },
        )
    )
    assert [log.msg for log in logs] == ["\u00e9tail"]


def test_byte_offset_for_last_n_lines():
    """Assert reverse newline counting returns the expected byte offsets."""
    content = b"line0\nline1\nline2\n"
    assert byte_offset_for_last_n_lines(content, 1) == len(b"line0\nline1\n")
    assert byte_offset_for_last_n_lines(content, 2) == len(b"line0\n")
    assert byte_offset_for_last_n_lines(content, 3) == 0
    assert byte_offset_for_last_n_lines(content, 10) == 0
    assert byte_offset_for_last_n_lines(b"line9", 1) == 0
    assert byte_offset_for_last_n_lines(b"line8\nline9", 1) == len(b"line8\n")
    assert byte_offset_for_last_n_lines(b"line8\nline9\n", 1) == len(b"line8\n")


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_returns_last_n_lines(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``tail_lines`` limits output to the trailing lines per stream."""
    tail_lines = 100
    total_lines = 150
    history = created_task_with_history
    payload = "".join(f"line{i}\n" for i in range(total_lines)).encode()
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(session, history, tail_lines=tail_lines)
    )
    combined = "".join(log.msg for log in logs)
    lines = [line for line in combined.split("\n") if line]

    assert len(lines) == tail_lines
    assert lines[0] == f"line{total_lines - tail_lines}"
    assert lines[-1] == f"line{total_lines - 1}"
    assert "line49" not in lines


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_merges_with_start_offset(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert resume offsets win when they are ahead of the tail-derived offset."""
    history = created_task_with_history
    payload = "".join(f"line{i}\n" for i in range(10)).encode()
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    history = await _reload(session, history)
    resume_offset = len("".join(f"line{i}\n" for i in range(8)).encode())
    logs = await _collect(
        iter_task_history_logs(
            session,
            history,
            start_offsets={"run-script": {TaskLogType.STDOUT: resume_offset}},
            tail_lines=5,
        )
    )
    combined = "".join(log.msg for log in logs)
    lines = [line for line in combined.split("\n") if line]

    assert lines == ["line8", "line9"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_legacy_blob(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``tail_lines`` applies to the legacy blob fallback path."""
    history = created_task_with_history
    legacy = {
        "run-script": {
            TaskLogType.STDOUT.value: "line0\nline1\nline2\nline3\n",
            TaskLogType.STDERR.value: "",
        }
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(legacy).encode())).decode()
    history.execution_request.tracking["task_logs"] = encoded
    saved = await TaskHistoryManager.save(
        session, history, flag_modified_fields=["execution_request"]
    )

    history = await _reload(session, saved)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=2))
    stdout_logs = [log for log in logs if log.type == TaskLogType.STDOUT]
    combined = "".join(log.msg for log in stdout_logs)

    assert combined == "line2\nline3\n"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_legacy_multibyte_boundary(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert legacy tail offsets map UTF-8 byte boundaries to ``str`` indices."""
    history = created_task_with_history
    msg = "ascii\n\u00e9\u00e9\u00e9tail\ndone\n"
    legacy = {
        "run-script": {
            TaskLogType.STDOUT.value: msg,
            TaskLogType.STDERR.value: "",
        }
    }
    encoded = base64.b64encode(gzip.compress(json.dumps(legacy).encode())).decode()
    history.execution_request.tracking["task_logs"] = encoded
    saved = await TaskHistoryManager.save(
        session, history, flag_modified_fields=["execution_request"]
    )

    history = await _reload(session, saved)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=2))
    combined = "".join(log.msg for log in logs if log.type == TaskLogType.STDOUT)

    assert combined == "\u00e9\u00e9\u00e9tail\ndone\n"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_multibyte_boundary(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert tail trimming respects UTF-8 byte offsets for multi-byte content."""
    history = created_task_with_history
    lines = ["ascii\n", "\u00e9\u00e9\u00e9tail\n", "done\n"]
    payload = "".join(lines).encode()
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=2))
    combined = "".join(log.msg for log in logs)

    assert combined == "\u00e9\u00e9\u00e9tail\ndone\n"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_none_returns_full_stream(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert omitting ``tail_lines`` keeps the pre-tail full-stream behaviour."""
    history = created_task_with_history
    payload = "".join(f"line{i}\n" for i in range(10)).encode()
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=payload,
        force_flush=True,
        producer_offset_after=len(payload),
    )

    history = await _reload(session, history)
    logs_without_tail = await _collect(iter_task_history_logs(session, history))
    logs_explicit_none = await _collect(
        iter_task_history_logs(session, history, tail_lines=None)
    )

    assert logs_without_tail == logs_explicit_none
    combined = "".join(log.msg for log in logs_without_tail)
    assert combined == payload.decode()
    assert "line0" in combined
    assert "line9" in combined


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_spans_multiple_chunks(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert tail offsets are resolved across several chunk rows."""
    history = created_task_with_history
    for index in range(6):
        await TaskHistoryLogWriter.append(
            session,
            history.id,
            source="run-script",
            stream=TaskLogType.STDOUT,
            new_bytes=f"line{index}\n".encode(),
            force_flush=True,
            producer_offset_after=(index + 1) * len(f"line{index}\n".encode()),
        )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=3))
    combined = "".join(log.msg for log in logs)
    lines = [line for line in combined.split("\n") if line]

    assert lines == ["line3", "line4", "line5"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_final_chunk_without_trailing_newline(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert tail respects the final unterminated line in the newest chunk."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"line7\nline8\n",
        force_flush=True,
        producer_offset_after=12,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"line9",
        force_flush=True,
        producer_offset_after=17,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=2))
    combined = "".join(log.msg for log in logs)
    lines = [line for line in combined.split("\n") if line]

    assert lines == ["line8", "line9"]


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_last_line_spans_chunks(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert tail finds the start of a logical line split across chunk rows."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"line7\nline8-part",
        force_flush=True,
        producer_offset_after=16,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"Brest",
        force_flush=True,
        producer_offset_after=21,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=1))
    combined = "".join(log.msg for log in logs)

    assert combined == "line8-partBrest"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_newline_only_chunk(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    r"""Assert a lone ``\\n`` chunk does not hide the preceding line (``b\\n``)."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"b",
        force_flush=True,
        producer_offset_after=1,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"\n",
        force_flush=True,
        producer_offset_after=2,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=1))
    combined = "".join(log.msg for log in logs)

    assert combined == "b\n"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_mid_line_chunk_boundary(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert the oldest retained line is not truncated at a byte chunk boundary."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"abc",
        force_flush=True,
        producer_offset_after=3,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"def\nlast\n",
        force_flush=True,
        producer_offset_after=12,
    )

    history = await _reload(session, history)
    logs = await _collect(iter_task_history_logs(session, history, tail_lines=2))
    combined = "".join(log.msg for log in logs)

    assert combined == "abcdef\nlast\n"


@pytest.mark.asyncio
async def test_iter_task_history_logs_tail_respects_source_filter(
    session: AsyncSession, created_task_with_history: TaskHistory
):
    """Assert ``source`` limits tail computation to the matching step."""
    history = created_task_with_history
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="run-script",
        stream=TaskLogType.STDOUT,
        new_bytes=b"run0\nrun1\nrun2\n",
        force_flush=True,
        producer_offset_after=18,
    )
    await TaskHistoryLogWriter.append(
        session,
        history.id,
        source="prepare",
        stream=TaskLogType.STDOUT,
        new_bytes=b"prep0\nprep1\nprep2\n",
        force_flush=True,
        producer_offset_after=18,
    )

    history = await _reload(session, history)
    logs = await _collect(
        iter_task_history_logs(session, history, source="run-script", tail_lines=2)
    )
    combined = "".join(log.msg for log in logs)

    assert combined == "run1\nrun2\n"
    assert "prep" not in combined


def test_decompress_legacy_logs_handles_corrupted_blob():
    """Assert a garbled base64/gzip/JSON blob returns an empty dict.

    Regression test for SEP-817: the reader used to propagate
    ``binascii.Error`` / ``zlib.error`` / ``json.JSONDecodeError`` and
    kill the Nomad sync loop.
    """
    corrupted_history = TaskHistory.model_construct(
        id=42,
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": "not-valid-base64!!!"}
        ),
    )
    assert decompress_legacy_logs(corrupted_history) == {}


def test_decompress_legacy_logs_handles_both_shapes():
    """Assert both base64+gzip strings and plain dicts decode the same way."""
    payload = {"run-script": {"stdout": "text", "stdout_last_offset": 4}}
    encoded = base64.b64encode(gzip.compress(json.dumps(payload).encode())).decode()

    dict_history = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": payload}
        )
    )
    str_history = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": encoded}
        )
    )

    assert decompress_legacy_logs(dict_history) == payload
    assert decompress_legacy_logs(str_history) == payload


def test_has_legacy_logs_skips_decode_for_truthy_blob():
    """Assert ``has_legacy_logs`` reports ``True`` without decoding the blob.

    Passes a "corrupted" blob (non-empty string that cannot be decoded) and
    asserts ``True`` -- if the helper were decoding the payload, the corrupted
    blob would return ``False`` (mirroring :func:`decompress_legacy_logs`).
    """
    corrupted_history = TaskHistory.model_construct(
        id=1,
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": "not-valid-base64!!!"}
        ),
    )
    assert has_legacy_logs(corrupted_history) is True


def test_has_legacy_logs_returns_false_for_empty_or_missing_blob():
    """Assert empty / missing / empty-dict ``task_logs`` all return ``False``."""
    missing = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={}
        )
    )
    empty_string = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": ""}
        )
    )
    empty_dict = TaskHistory.model_construct(
        execution_request=TaskHistory.model_fields["execution_request"].annotation(
            task="t", target="n", tracking={"task_logs": {}}
        )
    )

    assert has_legacy_logs(missing) is False
    assert has_legacy_logs(empty_string) is False
    assert has_legacy_logs(empty_dict) is False
