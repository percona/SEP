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

"""Define tests for the ATW diagnostics-send orchestrator and its housekeeping."""

import io
import json
import os
import zipfile
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import HTTPConflictException
from app.core.requests import RemoteAPI
from app.core.utils import json_serializer
from app.core.utils.date_time import utc_now
from app.sep.apps.atw.crud import AtwIncidentManager, AtwSendLogManager
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwSendLog,
    AtwSendStatusEnum,
)
from app.sep.apps.atw.send import (
    fail_stale_sends,
    purge_expired_bundles,
    run_send,
)
from app.sep.bundle_upload.plan import DeliveryPlan, DeliveryPlanError, StepRecord
from app.sep.bundle_upload.seam import BundleSource, UploadResult
from app.sep.config import sep_settings

_UPLOAD_DETAIL: dict[str, Any] = {"result": {"sys_id": "att-9", "size_bytes": 42}}
_EXPECTED_FILE_COUNT = 4
_EXPECTED_ENTRY_COUNT = 5
_STALE_ROW_COUNT = 2


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    """Yield ``content`` a byte at a time, as the Tasks API stream would.

    :param content: The file bytes to hand out.
    :return: An async iterator over single-byte chunks.
    """
    for index in range(len(content)):
        yield content[index : index + 1]


async def _blocks(content: bytes, size: int = 64 * 1024) -> AsyncIterator[bytes]:
    """Yield ``content`` in blocks, for payloads too large to hand out bytewise.

    :param content: The file bytes to hand out.
    :param size: The block size in bytes.
    :return: An async iterator over blocks.
    """
    for start in range(0, len(content), size):
        yield content[start : start + size]


class _FakeUploader:
    """Stand in for the delivery executor, recording what it was handed."""

    def __init__(
        self,
        *,
        result: UploadResult | None = None,
        error: Exception | None = None,
        step_observer: Callable[[StepRecord], None] | None = None,
    ) -> None:
        self.result = result or UploadResult(reference="att-9", detail=_UPLOAD_DETAIL)
        self.error = error
        self.step_observer = step_observer
        self.bundle_bytes: bytes | None = None
        self.manifest: dict[str, Any] | None = None
        self.case_ref: str | None = None
        self.called = False

    async def upload_bundle(
        self,
        *,
        source_ref: str,
        bundle: BundleSource,
        case_ref: str | None,
        manifest: dict[str, Any],
    ) -> UploadResult:
        """Record the send and return the configured result or raise."""
        self.called = True
        self.source_ref = source_ref
        self.bundle_bytes = bundle.content.read()
        self.bundle_size = bundle.size
        self.manifest = dict(manifest)
        self.case_ref = case_ref
        if self.error is not None:
            raise self.error
        return self.result


def _patch_tasks_api(mocker: MockerFixture, api: AsyncMock) -> AsyncMock:
    """Point the orchestrator at ``api``, yielding it from the auth context.

    :param mocker: The patching fixture.
    :param api: The faked Tasks API client.
    :return: The same client, for the caller to assert against.
    """
    api.auth.return_value.__enter__.return_value = api
    mocker.patch("app.sep.apps.atw.send.get_tasks_api", new=AsyncMock(return_value=api))
    return api


@pytest_asyncio.fixture(name="send_session")
async def send_session_fixture(
    mocker: MockerFixture, tmp_path: Path, delivery_plan: DeliveryPlan
) -> AsyncSession:
    """Yield a session whose maker and bundle directory the orchestrator uses.

    ``run_send`` opens its own session, so the maker it reaches for is pointed at
    this test engine; assertions then read the row back through a *separate*
    session from the same maker, which is what proves a ``detail`` write survived
    the commit rather than merely living on the in-flight instance.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session_maker = get_async_session_maker_from_engine(engine)
    mocker.patch(
        "app.sep.apps.atw.send.get_async_session_maker", return_value=session_maker
    )
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", delivery_plan)
    mocker.patch("app.sep.apps.atw.send.bundle_dir", return_value=tmp_path)
    try:
        async with session_maker() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture(name="tasks_api")
def tasks_api_fixture(mocker: MockerFixture) -> AsyncMock:
    """Provide a faked Tasks API client returning two files per execution."""
    api = AsyncMock(spec=RemoteAPI)
    api.get.return_value = {
        "stdout.log": {"is_dir": False, "size": 5},
        "diag/report.txt": {"is_dir": False, "size": 7},
    }
    api.stream_chunks.side_effect = lambda *_args, **_kwargs: _chunks(b"data!")
    _patch_tasks_api(mocker, api)
    return api


@pytest.fixture(name="uploader")
def uploader_fixture(mocker: MockerFixture) -> _FakeUploader:
    """Provide a fake delivery executor in place of the configured one."""
    fake = _FakeUploader()

    async def _factory(
        _plan: DeliveryPlan,
        *,
        step_observer: Callable[[StepRecord], None] | None = None,
    ) -> _FakeUploader:
        fake.step_observer = step_observer
        return fake

    mocker.patch("app.sep.apps.atw.send.get_delivery_executor", side_effect=_factory)
    return fake


async def _seed_send_log(
    session: AsyncSession,
    *,
    executions: list[dict[str, Any]] | None = None,
    case_ref: str = "CS0001",
) -> AtwSendLog:
    """Persist an incident and one pending send log selecting ``executions``.

    :param session: The database session.
    :param executions: The selected execution descriptors; two by default.
    :param case_ref: The support-case reference to snapshot on the row.
    :return: The persisted pending send log.
    """
    incident = await AtwIncidentManager.save(
        session, AtwIncident(created_by="alice", name="Prod outage")
    )
    selected = executions or [
        {"id": str(uuid4()), "task_history_id": 11, "snippet_filename": "cpu.sh"},
        {"id": str(uuid4()), "task_history_id": 12, "snippet_filename": "mem.sh"},
    ]
    return await AtwSendLogManager.save(
        session,
        AtwSendLog(
            incident_id=incident.id,
            case_ref=case_ref,
            requested_by="alice",
            detail={"executions": selected},
        ),
    )


async def _reload(session: AsyncSession, send_log_id: UUID) -> AtwSendLog:
    """Read a send log back through a session that never held the instance.

    :param session: The database session.
    :param send_log_id: The row to read.
    :return: The freshly-loaded row.
    """
    session.expunge_all()
    return await AtwSendLogManager.get_or_404(session, id=send_log_id)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tasks_api")
class TestRunSendHappyPath:
    """Cover a send that reaches the receiver and records its evidence."""

    async def test_bundles_every_selected_execution_and_records_success(
        self, send_session: AsyncSession, uploader: _FakeUploader, tmp_path: Path
    ) -> None:
        """Stage one zip entry per file plus a manifest, then finalize successfully."""
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.SUCCESS
        assert reloaded.started_at is not None
        assert reloaded.finished_at is not None
        assert reloaded.detail["upload_response"] == _UPLOAD_DETAIL
        assert reloaded.detail["upload_reference"] == "att-9"
        assert reloaded.detail["file_count"] == _EXPECTED_FILE_COUNT
        assert reloaded.detail["bundle_size"] > 0
        assert list(tmp_path.glob("*.zip")) == []

    async def test_zip_carries_a_manifest_and_per_execution_entries(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Namespace every file under its execution and describe them in a manifest."""
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        assert uploader.bundle_bytes is not None
        with zipfile.ZipFile(io.BytesIO(uploader.bundle_bytes)) as zf:
            names = sorted(zf.namelist())
            manifest = json.loads(zf.read("manifest.json"))

        assert len(names) == _EXPECTED_ENTRY_COUNT
        assert "11-cpu.sh/stdout.log" in names
        assert "12-mem.sh/diag/report.txt" in names
        assert manifest["case_ref"] == "CS0001"
        assert manifest["incident_name"] == "Prod outage"
        assert [entry["task_history_id"] for entry in manifest["executions"]] == [
            11,
            12,
        ]

    async def test_case_ref_snapshot_reaches_the_receiver(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Send the row's own case reference, not the incident's current one."""
        row = await _seed_send_log(send_session, case_ref="CS0999")

        await run_send(row.id)

        assert uploader.case_ref == "CS0999"

    async def test_resolution_steps_are_recorded_without_response_bodies(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Persist each observed step so a support engineer can read the trail."""
        row = await _seed_send_log(send_session)

        async def _upload(**kwargs: Any) -> UploadResult:
            assert uploader.step_observer is not None
            uploader.step_observer(StepRecord(name="lookup", status="running"))
            uploader.step_observer(
                StepRecord(name="lookup", status="success", outputs={"sys_id": "c-1"})
            )
            return UploadResult(reference="att-9", detail=_UPLOAD_DETAIL)

        uploader.upload_bundle = _upload

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.detail["steps"] == [
            {"name": "lookup", "status": "running", "outputs": None},
            {"name": "lookup", "status": "success", "outputs": {"sys_id": "c-1"}},
        ]

    async def test_a_non_json_upload_response_still_succeeds(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Treat a landed bundle as sent even when the receiver answers non-JSON."""
        uploader.result = UploadResult(reference=None, detail=None)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.SUCCESS
        assert reloaded.detail["upload_response"] is None
        assert reloaded.detail["upload_reference"] is None


@pytest.mark.asyncio
class TestRunSendArcnameCollisions:
    """Cover two executions producing identically-named files."""

    async def test_same_filename_in_two_executions_is_preserved_twice(
        self, send_session: AsyncSession, uploader: _FakeUploader, mocker: MockerFixture
    ) -> None:
        """Keep both same-named files by namespacing each under its execution."""
        api = AsyncMock(spec=RemoteAPI)
        api.get.return_value = {"stdout.log": {"is_dir": False, "size": 5}}
        api.stream_chunks.side_effect = lambda *_a, **_k: _chunks(b"data!")
        _patch_tasks_api(mocker, api)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        assert uploader.bundle_bytes is not None
        with zipfile.ZipFile(io.BytesIO(uploader.bundle_bytes)) as zf:
            names = sorted(name for name in zf.namelist() if name != "manifest.json")

        assert names == ["11-cpu.sh/stdout.log", "12-mem.sh/stdout.log"]


@pytest.mark.asyncio
class TestRunSendFailures:
    """Cover every failure family reaching a terminal failed row."""

    async def test_unconfigured_delivery_at_worker_time_fails_the_row(
        self, send_session: AsyncSession, mocker: MockerFixture
    ) -> None:
        """Fail cleanly when the receiver was unconfigured after the request."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert "not configured" in reloaded.detail["error"]

    @pytest.mark.usefixtures("uploader")
    async def test_a_files_listing_conflict_names_the_execution(
        self, send_session: AsyncSession, mocker: MockerFixture
    ) -> None:
        """Fail naming the execution whose output files are not ready."""
        api = AsyncMock(spec=RemoteAPI)
        api.get.side_effect = HTTPConflictException(detail="Task is still running")
        _patch_tasks_api(mocker, api)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert "11" in reloaded.detail["error"]

    async def test_zero_files_across_every_execution_sends_nothing(
        self, send_session: AsyncSession, uploader: _FakeUploader, mocker: MockerFixture
    ) -> None:
        """Refuse to upload a manifest-only bundle when nothing was collected."""
        api = AsyncMock(spec=RemoteAPI)
        api.get.return_value = {}
        _patch_tasks_api(mocker, api)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert "nothing to send" in reloaded.detail["error"].lower()
        assert uploader.called is False

    @pytest.mark.usefixtures("tasks_api")
    async def test_a_delivery_plan_error_is_recorded_verbatim(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Record the executor's own message when the plan cannot be carried out."""
        uploader.error = DeliveryPlanError("Bundle is 99 bytes, above the cap.")
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert reloaded.detail["error"] == "Bundle is 99 bytes, above the cap."

    @pytest.mark.usefixtures("tasks_api")
    async def test_a_failed_resolution_step_keeps_its_running_record(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Leave the failing step as the last recorded one so the log names it."""
        row = await _seed_send_log(send_session)

        async def _upload(**kwargs: Any) -> UploadResult:
            assert uploader.step_observer is not None
            uploader.step_observer(StepRecord(name="lookup", status="running"))
            raise HTTPConflictException(detail="ticket locked")

        uploader.upload_bundle = _upload

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert reloaded.detail["steps"] == [
            {"name": "lookup", "status": "running", "outputs": None}
        ]

    @pytest.mark.usefixtures("tasks_api")
    async def test_an_unexpected_error_still_writes_a_terminal_row(
        self, send_session: AsyncSession, uploader: _FakeUploader
    ) -> None:
        """Land a terminal row even when an unforeseen failure ends the send."""
        uploader.error = RuntimeError("upstream exploded")
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert "upstream exploded" in reloaded.detail["error"]

    @pytest.mark.usefixtures("tasks_api", "uploader")
    async def test_a_missing_row_exits_without_raising(
        self, send_session: AsyncSession
    ) -> None:
        """Exit quietly when the incident (and its row) was deleted mid-flight."""
        await run_send(uuid4())

        assert await AtwSendLogManager.count(send_session) == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("uploader")
class TestRunSendSizeCap:
    """Cover the configured bundle-size cap enforced while the zip is built."""

    async def test_an_oversized_bundle_aborts_before_any_upload(
        self,
        send_session: AsyncSession,
        uploader: _FakeUploader,
        mocker: MockerFixture,
        tmp_path: Path,
        delivery_plan: DeliveryPlan,
    ) -> None:
        """Stop mid-stream, delete the partial zip, and never reach the receiver."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            delivery_plan.model_copy(update={"max_bundle_size_mb": 1}),
        )
        api = AsyncMock(spec=RemoteAPI)
        api.get.return_value = {"big.bin": {"is_dir": False, "size": 1}}
        api.stream_chunks.side_effect = lambda *_a, **_k: _blocks(
            os.urandom(2 * 1024 * 1024)
        )
        _patch_tasks_api(mocker, api)
        row = await _seed_send_log(send_session)

        await run_send(row.id)

        reloaded = await _reload(send_session, row.id)
        assert reloaded.status is AtwSendStatusEnum.FAILED
        assert "1 MiB" in reloaded.detail["error"]
        assert uploader.called is False
        assert list(tmp_path.glob("*.zip")) == []


@pytest.mark.asyncio
class TestFailStaleSends:
    """Cover the sweep that drives abandoned sends to a terminal status."""

    async def test_drives_aged_active_rows_to_failed(
        self, send_session: AsyncSession
    ) -> None:
        """Fail pending and running rows whose worker never came back."""
        incident = await AtwIncidentManager.save(
            send_session, AtwIncident(created_by="alice")
        )
        aged = utc_now() - timedelta(hours=4)
        for status in (AtwSendStatusEnum.PENDING, AtwSendStatusEnum.RUNNING):
            await AtwSendLogManager.save(
                send_session,
                AtwSendLog(
                    incident_id=incident.id,
                    case_ref="CS0001",
                    requested_by="alice",
                    status=status,
                    created_at=aged,
                    detail={},
                ),
            )

        swept = await fail_stale_sends(timedelta(hours=1))

        send_session.expunge_all()
        rows = await AtwSendLogManager.list(send_session, incident_id=incident.id)
        assert swept == _STALE_ROW_COUNT
        assert {row.status for row in rows} == {AtwSendStatusEnum.FAILED}
        assert all("worker" in row.detail["error"].lower() for row in rows)

    async def test_leaves_fresh_and_terminal_rows_alone(
        self, send_session: AsyncSession
    ) -> None:
        """Spare a young in-flight send and any row that already finished."""
        incident = await AtwIncidentManager.save(
            send_session, AtwIncident(created_by="alice")
        )
        fresh = await AtwSendLogManager.save(
            send_session,
            AtwSendLog(
                incident_id=incident.id,
                case_ref="CS0001",
                requested_by="alice",
                status=AtwSendStatusEnum.RUNNING,
                detail={},
            ),
        )
        done = await AtwSendLogManager.save(
            send_session,
            AtwSendLog(
                incident_id=incident.id,
                case_ref="CS0002",
                requested_by="alice",
                status=AtwSendStatusEnum.SUCCESS,
                created_at=utc_now() - timedelta(hours=4),
                detail={},
            ),
        )

        swept = await fail_stale_sends(timedelta(hours=1))

        send_session.expunge_all()
        assert swept == 0
        assert (
            await AtwSendLogManager.get_or_404(send_session, id=fresh.id)
        ).status is AtwSendStatusEnum.RUNNING
        assert (
            await AtwSendLogManager.get_or_404(send_session, id=done.id)
        ).status is AtwSendStatusEnum.SUCCESS


class TestPurgeExpiredBundles:
    """Cover the on-disk sweep of staged bundles."""

    def test_removes_expired_bundles_and_keeps_fresh_ones(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Reap a bundle past its TTL while leaving a just-written one in place."""
        mocker.patch("app.sep.apps.atw.send.bundle_dir", return_value=tmp_path)
        expired = tmp_path / "old.zip"
        expired.write_bytes(b"old")
        os.utime(expired, (0, 0))
        fresh = tmp_path / "new.zip"
        fresh.write_bytes(b"new")

        removed = purge_expired_bundles(3600)

        assert removed == 1
        assert not expired.exists()
        assert fresh.exists()

    def test_a_missing_directory_purges_nothing(
        self, mocker: MockerFixture, tmp_path: Path
    ) -> None:
        """Treat an unused staging directory as empty rather than an error."""
        mocker.patch(
            "app.sep.apps.atw.send.bundle_dir", return_value=tmp_path / "absent"
        )

        assert purge_expired_bundles(3600) == 0
