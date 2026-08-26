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

"""Test the scheduled inventory-collection job."""

import re
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import pytest
from pydantic import SecretStr
from pytest_mock import MockerFixture
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.inventory.constants import RetirableEntityName
from app.sep.apps.inventory import collection
from app.sep.apps.inventory.collection import (
    run_inventory_collection,
    run_scheduled_inventory_collection,
)
from app.sep.apps.meta_keys import SERVICE_ID_META_KEY
from app.sep.apps.mysql_backups.crud import MysqlBackupRunManager
from app.sep.apps.mysql_backups.inventory_references import (
    referenced_inventory_entities,
)
from app.sep.apps.mysql_backups.models import MysqlBackupRun
from app.sep.crud import SyncEntityAbsenceManager
from app.sep.models import SyncEntityAbsenceWrite, SyncInventoryEntityTypeEnum
from app.tasks.crud import TaskManager
from tests.app.factories import TaskFactory

API_KEY = "internal-token"
BATCH_SIZE = 42
BATCH_CAP = 3
TWO_BATCHES = 2
SYNCER = "app.sep.sync.syncers.pmm.PMMSyncer"


def _session_maker(session: AsyncSession) -> Callable[[], Any]:
    """Return a session-maker factory yielding one already-built session.

    :param session: The session every ``async with`` block should receive.
    :return: A zero-argument callable standing in for a session maker.
    """

    @asynccontextmanager
    async def maker():
        yield session

    return lambda: maker()


class RecordingInventoryClient:
    """Stand in for the Inventory API, recording every collect call.

    The HTTP client is the job's boundary, so it is the one thing replaced. The
    stub also snapshots how many absence-ledger rows survive at the moment each
    call arrives, which is what lets a test assert the *ordering* of the clear
    against the delete rather than only the end state.

    :param batches: One ``(deleted, remaining)`` pair per batch the API should
        answer with; the last pair repeats once exhausted.
    :param ledger_probe: Called on each request to snapshot observable state.
    """

    def __init__(
        self,
        batches: list[tuple[dict[str, list[int]], bool]],
        ledger_probe: Callable[[], Any] | None = None,
    ) -> None:
        self.batches = batches
        self.ledger_probe = ledger_probe
        self.calls: list[dict[str, Any]] = []
        self.ledger_at_call: list[Any] = []
        self.on_dry_run: Callable[[], Any] | None = None

    @contextmanager
    def auth(self, api_key: str, auth_scheme: str = "Bearer"):
        """Record the credential the job authenticated with."""
        self.api_key = api_key
        yield self

    @asynccontextmanager
    async def hold(self):
        """Reproduce the real client's in-flight accounting block."""
        yield self

    async def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        """Answer one collect call from the queued batches."""
        self.calls.append({"path": path, **json})
        if self.ledger_probe is not None:
            self.ledger_at_call.append(await self.ledger_probe())
        index = min(len(self.batches) - 1, (len(self.calls) - 1) // 2)
        deleted, remaining = self.batches[index]
        if json["dry_run"] and self.on_dry_run is not None:
            await self.on_dry_run()
        return {"deleted": deleted, "remaining": remaining}

    @property
    def dry_run_calls(self) -> list[dict[str, Any]]:
        """Return the calls the job issued with ``dry_run`` set."""
        return [call for call in self.calls if call["dry_run"]]

    @property
    def real_calls(self) -> list[dict[str, Any]]:
        """Return the calls the job issued that actually delete."""
        return [call for call in self.calls if not call["dry_run"]]


def _batch(node_ids: list[int], *, remaining: bool = False) -> tuple[dict, bool]:
    """Build one collect response body naming the given nodes.

    :param node_ids: The node ids the API should report as collected.
    :param remaining: Whether the API should report more batches waiting.
    :return: The ``(deleted, remaining)`` pair the stub answers with.
    """
    return (
        {"table": [], "schema": [], "service": [], "node": node_ids},
        remaining,
    )


@pytest.fixture
def no_providers(mocker: MockerFixture) -> None:
    """Declare that no app contributes inventory references."""
    mocker.patch.object(collection, "collect_inventory_reference_providers", list)


@pytest.fixture
def task_databases(
    mocker: MockerFixture,
    session: AsyncSession,
    celery_beat_session: AsyncSession,
) -> None:
    """Point the built-in task-envelope scan at the test databases.

    Real but empty by default, so a test that wants an envelope in the retained
    set creates the row rather than replacing the scan.
    """
    mocker.patch.object(
        collection, "get_tasks_session_maker", return_value=_session_maker(session)
    )
    mocker.patch.object(
        collection,
        "get_beat_session_maker",
        return_value=_session_maker(celery_beat_session),
    )


@pytest.fixture
def sep_database(mocker: MockerFixture, session: AsyncSession) -> None:
    """Point the job's SEP reads and ledger writes at the test database."""
    mocker.patch.object(
        collection, "get_sep_session_maker", return_value=_session_maker(session)
    )


@pytest.fixture
def one_syncer(mocker: MockerFixture) -> None:
    """Configure exactly one syncer so the ledger clear has a key to use."""
    mocker.patch.object(
        collection.sep_settings, "SYNCERS", [type("Opt", (), {"syncer": SYNCER})()]
    )


def _install_client(
    mocker: MockerFixture, client: RecordingInventoryClient
) -> RecordingInventoryClient:
    """Make the job resolve the given stub instead of a real HTTP client.

    :param mocker: The pytest-mock fixture.
    :param client: The stub to hand back.
    :return: The same stub, for the test to assert on.
    """
    mocker.patch.object(collection, "get_inventory_api_standalone", return_value=client)
    return client


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database", "one_syncer")
class TestRunInventoryCollection:
    """Cover the batching, ordering and cutoff discipline of one run."""

    async def test_a_single_batch_ends_the_run(self, mocker: MockerFixture) -> None:
        """Stop after one batch when the API reports nothing remaining."""
        client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

        await run_inventory_collection(API_KEY)

        assert len(client.dry_run_calls) == 1
        assert len(client.real_calls) == 1

    async def test_the_run_continues_while_entities_remain(
        self, mocker: MockerFixture
    ) -> None:
        """Issue a second batch when the first reports more waiting."""
        client = _install_client(
            mocker,
            RecordingInventoryClient([_batch([1], remaining=True), _batch([2])]),
        )

        await run_inventory_collection(API_KEY)

        assert len(client.real_calls) == TWO_BATCHES

    async def test_the_run_stops_at_the_batch_cap(self, mocker: MockerFixture) -> None:
        """End normally at the cap rather than looping while more remain."""
        mocker.patch.object(
            collection.inventory_app_settings, "COLLECTION_MAX_BATCHES", BATCH_CAP
        )
        client = _install_client(
            mocker, RecordingInventoryClient([_batch([1], remaining=True)])
        )

        await run_inventory_collection(API_KEY)

        assert len(client.real_calls) == BATCH_CAP

    async def test_the_cutoff_is_pinned_for_the_whole_run(
        self, mocker: MockerFixture
    ) -> None:
        """Send one identical ``retired_before`` on every call of the run."""
        client = _install_client(
            mocker,
            RecordingInventoryClient([_batch([1], remaining=True), _batch([2])]),
        )

        await run_inventory_collection(API_KEY)

        assert len({call["retired_before"] for call in client.calls}) == 1

    async def test_the_batch_size_is_sent_as_the_limit(
        self, mocker: MockerFixture
    ) -> None:
        """Ask the API for no more than the configured batch size."""
        mocker.patch.object(
            collection.inventory_app_settings, "COLLECTION_BATCH_SIZE", BATCH_SIZE
        )
        client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

        await run_inventory_collection(API_KEY)

        assert client.calls[0]["limit"] == BATCH_SIZE

    async def test_the_run_authenticates_with_the_given_token(
        self, mocker: MockerFixture
    ) -> None:
        """Carry the internal token into the Inventory API calls."""
        client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

        await run_inventory_collection(API_KEY)

        assert client.api_key == API_KEY


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database", "one_syncer")
async def test_the_ledger_is_cleared_before_the_delete(
    mocker: MockerFixture, session: AsyncSession
) -> None:
    """Drop the absence rows before the delete, not after it.

    Clearing first is the only order with no crash window, and it is safe
    because the syncer cannot re-record an absence for an already-retired
    entity. The stub snapshots the surviving ledger rows as each call arrives,
    so this asserts the ordering rather than only the end state.
    """
    await SyncEntityAbsenceManager.create(
        session,
        SyncEntityAbsenceWrite(
            syncer=SYNCER,
            entity_type=SyncInventoryEntityTypeEnum.NODE,
            entity_id=1,
        ),
    )

    async def probe() -> int:
        return await SyncEntityAbsenceManager.count(session)

    client = _install_client(
        mocker, RecordingInventoryClient([_batch([1])], ledger_probe=probe)
    )

    await run_inventory_collection(API_KEY)

    assert client.ledger_at_call == [1, 0]


@pytest.mark.asyncio
@pytest.mark.usefixtures("task_databases", "sep_database", "one_syncer")
async def test_a_raising_provider_deletes_nothing(mocker: MockerFixture) -> None:
    """Abort the run instead of deleting against a partial retained set."""

    async def broken_provider(_session: AsyncSession) -> Mapping:
        raise RuntimeError("provider is down")

    mocker.patch.object(
        collection,
        "collect_inventory_reference_providers",
        return_value=[broken_provider],
    )
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    with pytest.raises(RuntimeError, match="provider is down"):
        await run_inventory_collection(API_KEY)

    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("task_databases", "sep_database", "one_syncer")
async def test_an_empty_provider_result_is_not_a_skip(
    mocker: MockerFixture,
) -> None:
    """Treat "nothing referenced" as a licence to collect, not as an abort."""

    async def empty_provider(_session: AsyncSession) -> Mapping:
        return {}

    mocker.patch.object(
        collection,
        "collect_inventory_reference_providers",
        return_value=[empty_provider],
    )
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_inventory_collection(API_KEY)

    assert len(client.real_calls) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("task_databases", "sep_database", "one_syncer")
async def test_provider_ids_are_sent_as_keep(mocker: MockerFixture) -> None:
    """Forward every declared reference into the retained set."""

    async def provider(_session: AsyncSession) -> Mapping:
        return {RetirableEntityName.SERVICE: {5, 9}}

    mocker.patch.object(
        collection, "collect_inventory_reference_providers", return_value=[provider]
    )
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_inventory_collection(API_KEY)

    assert client.calls[0]["keep"]["service"] == [5, 9]


@pytest.mark.asyncio
@pytest.mark.usefixtures("task_databases", "sep_database", "one_syncer")
async def test_a_run_recorded_after_the_dry_run_still_survives(
    mocker: MockerFixture, session: AsyncSession
) -> None:
    """Keep a service whose backup run lands between the two calls of a batch.

    The retained set is computed once, before the dry run, and the catalog is
    still empty at that point — so the id can only be retained by the ``Task``
    envelope scan. A recorder can fire only for a task that already existed
    then, which is what closes the window without a lease.
    """
    await TaskManager.save(
        session,
        TaskFactory.build(
            name="backup-a",
            data={"task": "run-command", "meta": {SERVICE_ID_META_KEY: 5}},
            deleted_at=None,
        ),
    )
    mocker.patch.object(
        collection,
        "collect_inventory_reference_providers",
        return_value=[referenced_inventory_entities],
    )
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    async def record_run() -> None:
        await MysqlBackupRunManager.save(
            session,
            MysqlBackupRun(
                task_history_id=1,
                service_name="svc-a",
                service_id=5,
                backup_type="M",
            ),
        )

    client.on_dry_run = record_run

    await run_inventory_collection(API_KEY)

    assert await MysqlBackupRunManager.count(session) == 1
    assert client.real_calls[0]["keep"]["service"] == [5]


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database")
async def test_no_configured_syncer_still_deletes(mocker: MockerFixture) -> None:
    """Collect normally when there is no absence ledger to clear."""
    mocker.patch.object(collection.sep_settings, "SYNCERS", [])
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_inventory_collection(API_KEY)

    assert len(client.real_calls) == 1


@pytest.mark.asyncio
async def test_a_missing_internal_token_is_refused(mocker: MockerFixture) -> None:
    """Refuse to run without the credential the Inventory API requires."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)

    with pytest.raises(ValueError, match=re.escape("SEP_INTERNAL_TOKEN")):
        await run_scheduled_inventory_collection()


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database", "one_syncer")
async def test_the_configured_token_reaches_the_api(mocker: MockerFixture) -> None:
    """Authenticate the scheduled run with the configured internal token."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(API_KEY))
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_scheduled_inventory_collection()

    assert client.api_key == API_KEY


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database", "one_syncer")
async def test_clearing_one_entity_type_leaves_a_colliding_id_alone(
    mocker: MockerFixture, session: AsyncSession
) -> None:
    """Clear only the node's ledger row when a service shares its id.

    Nodes and services are numbered from separate sequences and collide freely,
    so the ledger key is the full ``(syncer, entity_type, entity_id)`` triple.
    """
    for entity_type in (
        SyncInventoryEntityTypeEnum.NODE,
        SyncInventoryEntityTypeEnum.SERVICE,
    ):
        await SyncEntityAbsenceManager.create(
            session,
            SyncEntityAbsenceWrite(syncer=SYNCER, entity_type=entity_type, entity_id=1),
        )
    _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_inventory_collection(API_KEY)

    surviving = await SyncEntityAbsenceManager.list(session)
    assert [row.entity_type for row in surviving] == [
        SyncInventoryEntityTypeEnum.SERVICE
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("no_providers", "task_databases", "sep_database", "one_syncer")
async def test_the_real_call_asks_for_a_delete_explicitly(
    mocker: MockerFixture,
) -> None:
    """Send ``dry_run`` on both calls of a batch, never relying on its default.

    The endpoint defaults to reporting, so the delete half of a batch is only a
    delete because the job says so.
    """
    client = _install_client(mocker, RecordingInventoryClient([_batch([1])]))

    await run_inventory_collection(API_KEY)

    assert [call["dry_run"] for call in client.calls] == [True, False]
