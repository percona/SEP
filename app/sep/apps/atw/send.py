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

"""Build and deliver an incident's diagnostics bundle, recording every attempt.

The ``atw_send_log`` row *is* the job: the API creates it and enqueues the Celery
task with its id, and this module drives it to a terminal status. Because the
receiver's credentials can create attachments but not read them back, the row's
``detail`` is the only evidence a send ever landed -- so every write assigns a
fresh mapping and flags the JSON column, and a broad terminal guard makes sure no
failure family leaves a row stuck mid-flight.
"""

__all__ = [
    "AtwBundleSizeError",
    "AtwNothingToSendError",
    "AtwSendError",
    "bundle_dir",
    "fail_stale_sends",
    "purge_expired_bundles",
    "run_send",
]

import logging
import time
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import Any, BinaryIO
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.core.utils import json_serializer
from app.core.utils.date_time import utc_now
from app.sep.apps.atw.config import atw_settings
from app.sep.apps.atw.crud import AtwIncidentManager, AtwSendLogManager
from app.sep.apps.atw.models import AtwSendLog, AtwSendStatusEnum
from app.sep.apps.inventory.sync import require_internal_token
from app.sep.bundle_upload.factory import get_delivery_executor
from app.sep.bundle_upload.plan import StepRecord
from app.sep.bundle_upload.seam import BundleSource
from app.sep.config import sep_settings
from app.sep.db import get_async_session_maker
from app.tasks.config import tasks_settings

logger = logging.getLogger(__name__)

_BYTES_PER_MIB = 1024 * 1024
_MANIFEST_ARCNAME = "manifest.json"
_BUNDLE_SUFFIX = ".zip"
_UNCONFIGURED_ERROR = "Diagnostics delivery is not configured"
_NOTHING_TO_SEND_ERROR = (
    "The selected executions produced no output files -- nothing to send."
)
_WORKER_LOST_ERROR = (
    "The worker running this send did not report back in time; it was most "
    "likely lost. Re-send to try again."
)


class AtwSendError(Exception):
    """Signal that a diagnostics send cannot be completed as requested."""


class AtwBundleSizeError(AtwSendError):
    """Signal that a bundle grew past the configured cap while being built."""


class AtwNothingToSendError(AtwSendError):
    """Signal that the selected executions produced no files to send."""


def bundle_dir() -> Path:
    """Return the configured bundle staging directory.

    :return: Path to the staging directory.
    """
    return Path(atw_settings.bundle_dir)


class _CappedWriter:
    """Wrap a binary handle, refusing writes once the file outgrows a cap.

    The cap is enforced *during* the build rather than on the finished file, so a
    runaway bundle stops mid-stream instead of after the whole thing is staged.
    """

    def __init__(self, handle: BinaryIO, cap_mb: int) -> None:
        """Bind the wrapper to the handle it guards.

        :param handle: The open binary handle to write through.
        :param cap_mb: The largest the file may grow, in mebibytes.
        """
        self._handle = handle
        self._cap_mb = cap_mb
        self._cap_bytes = cap_mb * _BYTES_PER_MIB

    def write(self, data: bytes) -> int:
        """Write ``data`` through, then refuse if the file outgrew its cap.

        :param data: The bytes to write.
        :return: The number of bytes written.
        :raises AtwBundleSizeError: When the file has grown past the cap.
        """
        written = self._handle.write(data)
        if self._handle.tell() > self._cap_bytes:
            raise AtwBundleSizeError(
                f"Bundle exceeded the configured {self._cap_mb} MiB limit while "
                f"being built."
            )
        return written

    def tell(self) -> int:
        """Return the handle's current offset.

        :return: The offset in bytes.
        """
        return self._handle.tell()

    def seek(self, offset: int, whence: int = 0) -> int:
        """Seek the underlying handle.

        :param offset: The target offset.
        :param whence: How to interpret ``offset``.
        :return: The new absolute offset.
        """
        return self._handle.seek(offset, whence)

    def seekable(self) -> bool:
        """Report the handle as seekable so :mod:`zipfile` patches its headers.

        :return: Whether the underlying handle supports seeking.
        """
        return self._handle.seekable()

    def flush(self) -> None:
        """Flush the underlying handle."""
        self._handle.flush()


async def get_tasks_api() -> RemoteAPI:
    """Return the pooled Tasks API client the worker streams files through.

    :return: The Tasks API client, unauthenticated.
    """
    return await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        logger_name="tasks_api",
    )


def _execution_prefix(execution: dict[str, Any]) -> str:
    """Return the zip directory namespacing one execution's files.

    Files are listed per execution, so two executions can each produce a
    ``stdout.log``; prefixing every entry keeps both and lets the manifest map a
    file back to the execution that produced it.

    :param execution: The selected execution descriptor.
    :return: The per-execution arcname prefix, without a trailing separator.
    """
    return f"{execution['task_history_id']}-{execution['snippet_filename']}"


async def _add_execution_files(
    archive: zipfile.ZipFile, tasks_api: RemoteAPI, execution: dict[str, Any]
) -> list[dict[str, Any]]:
    """Stream one execution's output files into the archive.

    Entries are written strictly one at a time: :mod:`zipfile` rejects a second
    open writable member while one is still open.

    :param archive: The open archive to write into.
    :param tasks_api: The authenticated Tasks API client.
    :param execution: The selected execution descriptor.
    :return: One manifest entry per file written.
    :raises AtwSendError: When the execution's files cannot be listed or streamed
        -- most often because it has not finished, or its output has aged out of
        the executor node.
    :raises AtwBundleSizeError: Propagated from the archive's capped writer when
        this execution's files push the bundle past the plan's cap.
    """
    task_history_id = execution["task_history_id"]
    try:
        listing = await tasks_api.get(f"/history/{task_history_id}/files/") or {}
    except (HTTPException, OSError) as exc:
        raise AtwSendError(
            f"Could not list output files for execution {task_history_id} "
            f"({execution['snippet_filename']}): {_error_message(exc)}"
        ) from exc

    prefix = _execution_prefix(execution)
    written = []
    for path, metadata in listing.items():
        arcname = f"{prefix}/{path.lstrip('/')}"
        try:
            size = await _write_entry(
                archive, tasks_api, task_history_id, path, arcname
            )
        except (HTTPException, OSError) as exc:
            raise AtwSendError(
                f"Could not read {path!r} from execution {task_history_id} "
                f"({execution['snippet_filename']}): {_error_message(exc)}"
            ) from exc
        written.append(
            {
                "path": path,
                "arcname": arcname,
                "size": size,
                "is_dir": bool(metadata.get("is_dir")),
            }
        )
    return written


async def _write_entry(
    archive: zipfile.ZipFile,
    tasks_api: RemoteAPI,
    task_history_id: int,
    path: str,
    arcname: str,
) -> int:
    """Stream one upstream file into one archive member.

    :param archive: The open archive to write into.
    :param tasks_api: The authenticated Tasks API client.
    :param task_history_id: The execution the file belongs to.
    :param path: The file's path within that execution's output.
    :param arcname: The entry name to write it under.
    :return: The number of bytes streamed.
    :raises AtwBundleSizeError: Propagated from the archive's capped writer when
        this file pushes the bundle past the plan's cap.
    :raises HTTPException: Propagates the Tasks API's error status for the stream.
    :raises OSError: Propagates a connection or timeout failure mid-stream.
    """
    size = 0
    with archive.open(arcname, "w", force_zip64=True) as entry:
        async for chunk in tasks_api.stream_chunks(
            f"/history/{task_history_id}/file/", params={"path": path}
        ):
            size += len(chunk)
            entry.write(chunk)
    return size


def _build_manifest(
    row: AtwSendLog, incident_name: str, executions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Describe the bundle's contents for the receiver and the send log.

    :param row: The send log this bundle belongs to.
    :param incident_name: The incident's human-readable label.
    :param executions: One entry per execution, carrying its written files.
    :return: The manifest mapping.
    """
    return {
        "incident_id": str(row.incident_id),
        "incident_name": incident_name,
        "case_ref": row.case_ref,
        "requested_by": row.requested_by,
        "generated_at": utc_now().isoformat(),
        "executions": executions,
    }


async def _stage_bundle(
    path: Path, row: AtwSendLog, incident_name: str, tasks_api: RemoteAPI
) -> tuple[int, dict[str, Any]]:
    """Stage the incident's diagnostics as one zip on local disk.

    :param path: Where to write the archive.
    :param row: The send log naming the selected executions.
    :param incident_name: The incident's human-readable label.
    :param tasks_api: The authenticated Tasks API client.
    :return: The number of collected files and the bundle manifest.
    :raises AtwBundleSizeError: When the archive outgrows the plan's cap.
    :raises AtwNothingToSendError: When no execution produced a file.
    :raises AtwSendError: When an execution's files cannot be collected.
    """
    cap_mb = sep_settings.DIAGNOSTICS_DELIVERY.max_bundle_size_mb
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest_executions = []
    file_count = 0
    with (
        path.open("wb") as handle,
        zipfile.ZipFile(
            _CappedWriter(handle, cap_mb), "w", zipfile.ZIP_DEFLATED
        ) as archive,
    ):
        for execution in row.detail.get("executions", []):
            files = await _add_execution_files(archive, tasks_api, execution)
            file_count += len(files)
            manifest_executions.append({**execution, "files": files})
        if not file_count:
            raise AtwNothingToSendError(_NOTHING_TO_SEND_ERROR)
        manifest = _build_manifest(row, incident_name, manifest_executions)
        archive.writestr(_MANIFEST_ARCNAME, json_serializer(manifest))
    return file_count, manifest


async def _persist(
    session: AsyncSession, row: AtwSendLog, detail: dict[str, Any], **fields: Any
) -> None:
    """Write a fresh ``detail`` mapping and the given columns to the row.

    A JSON column is not change-tracked through in-place mutation, so ``detail``
    is always replaced wholesale and flagged -- a silently-dropped write here
    would lose the only record that a bundle reached the receiver.

    :param session: The database session.
    :param row: The send log to update.
    :param detail: The evidence mapping to store.
    :param fields: Column values to set alongside it.
    """
    for name, value in fields.items():
        setattr(row, name, value)
    row.detail = detail
    await AtwSendLogManager.save(session, row, flag_modified_fields=["detail"])


async def run_send(send_log_id: UUID) -> None:
    """Build and deliver the bundle one send log describes.

    Every failure family lands as a ``FAILED`` row carrying its reason: the row is
    the only place a support engineer can learn what happened, so the terminal
    write is guaranteed rather than best-effort.

    :param send_log_id: The send log driving this attempt.
    """
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        row = await AtwSendLogManager.first(session, id=send_log_id)
        if row is None:
            logger.info(
                "Send log %s is gone; its incident was most likely deleted.",
                send_log_id,
            )
            return
        await _run_send_for_row(session, row)


async def _run_send_for_row(session: AsyncSession, row: AtwSendLog) -> None:
    """Drive one send log from pending to a terminal status.

    :param session: The database session.
    :param row: The send log to drive.
    """
    detail = dict(row.detail)
    if sep_settings.DIAGNOSTICS_DELIVERY is None:
        await _fail(session, row, detail, [], _UNCONFIGURED_ERROR)
        return

    incident = await AtwIncidentManager.get_or_404(session, id=row.incident_id)
    incident_name = incident.name
    await _persist(
        session, row, detail, status=AtwSendStatusEnum.RUNNING, started_at=utc_now()
    )

    steps: list[dict[str, Any]] = []
    path = bundle_dir() / f"{row.id}-{uuid4().hex}{_BUNDLE_SUFFIX}"
    try:
        client = await get_tasks_api()
        with client.auth(require_internal_token()) as tasks_api:
            file_count, manifest = await _stage_bundle(
                path, row, incident_name, tasks_api
            )
        size = path.stat().st_size
        executor = await get_delivery_executor(
            sep_settings.DIAGNOSTICS_DELIVERY,
            step_observer=lambda record: steps.append(_step_detail(record)),
        )
        with path.open("rb") as handle:
            result = await executor.upload_bundle(
                source_ref=f"atw-incident/{row.incident_id}",
                bundle=BundleSource(filename=path.name, content=handle, size=size),
                case_ref=row.case_ref,
                manifest=manifest,
            )
    except Exception as exc:  # noqa: BLE001 -- every family must land terminally
        logger.warning("Diagnostics send %s failed.", row.id, exc_info=True)
        await _fail(session, row, detail, steps, _error_message(exc))
        return
    finally:
        path.unlink(missing_ok=True)

    await _persist(
        session,
        row,
        {
            **detail,
            "steps": steps,
            "upload_response": None if result.detail is None else dict(result.detail),
            "upload_reference": result.reference,
            "bundle_size": size,
            "file_count": file_count,
        },
        status=AtwSendStatusEnum.SUCCESS,
        finished_at=utc_now(),
    )


async def _fail(
    session: AsyncSession,
    row: AtwSendLog,
    detail: dict[str, Any],
    steps: list[dict[str, Any]],
    error: str,
) -> None:
    """Write the terminal failed row carrying the reason the send ended.

    :param session: The database session.
    :param row: The send log to finalize.
    :param detail: The evidence gathered before the failure.
    :param steps: The resolution steps observed so far.
    :param error: The reason to record.
    """
    await _persist(
        session,
        row,
        {**detail, "steps": steps, "error": error},
        status=AtwSendStatusEnum.FAILED,
        finished_at=utc_now(),
    )


def _step_detail(record: StepRecord) -> dict[str, Any]:
    """Render one observed resolution step for the send log.

    :param record: The step transition the executor reported.
    :return: The JSON-serializable step entry.
    """
    return {
        "name": record.name,
        "status": record.status,
        "outputs": None if record.outputs is None else dict(record.outputs),
    }


def _error_message(exc: Exception) -> str:
    """Return the reason to record against a failed send.

    :param exc: The exception that ended the attempt.
    :return: A message a support engineer can act on.
    """
    detail = getattr(exc, "detail", None)
    return str(detail) if detail else str(exc)


def purge_expired_bundles(ttl_seconds: int) -> int:
    """Delete staged bundles whose mtime is older than ``ttl_seconds``.

    :param ttl_seconds: Maximum bundle age in seconds.
    :return: The number of bundles removed.
    """
    staging = bundle_dir()
    if not staging.is_dir():
        return 0
    cutoff = time.time() - ttl_seconds
    removed = 0
    for path in staging.glob(f"*{_BUNDLE_SUFFIX}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                removed += 1
        except OSError:
            logger.exception("Failed to purge diagnostics bundle %s", path)
    return removed


async def fail_stale_sends(stale_after: timedelta) -> int:
    """Drive sends abandoned by a lost worker to a terminal failed status.

    Both non-terminal statuses need a driver: a worker killed between the enqueue
    and the terminal write leaves a row nothing else would ever advance, and the
    UI would poll it forever. Rows are aged from when they were last known to
    progress -- ``started_at`` once a worker picked one up, ``created_at`` while
    still queued.

    :param stale_after: How long a send may stay non-terminal before it is failed.
    :return: The number of sends failed.
    """
    cutoff = utc_now() - stale_after
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        rows = await AtwSendLogManager.list(
            session,
            col(AtwSendLog.status).in_(AtwSendStatusEnum.active_statuses()),
            func.coalesce(col(AtwSendLog.started_at), col(AtwSendLog.created_at))
            < cutoff,
        )
        for row in rows:
            await _persist(
                session,
                row,
                {**row.detail, "error": _WORKER_LOST_ERROR},
                status=AtwSendStatusEnum.FAILED,
                finished_at=utc_now(),
            )
    if rows:
        logger.info("Failed %d stale diagnostics send(s).", len(rows))
    return len(rows)
