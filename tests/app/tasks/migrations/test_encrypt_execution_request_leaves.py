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

"""Tests for the Tasks-track execution-request leaf-encryption data migration.

The Alembic legs run on the SQLite fixture the track ships. The rewrite is also
exercised on a real PostgreSQL engine, because the migration's whole operation is
a JSONB read and rewrite and rendering the statement proves neither half.
"""

import json
from datetime import datetime, UTC
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel

from app.core.db.sql_types import AutoJSON
from app.core.encryption import decrypt, encrypt, is_encrypted
from app.tasks import alembic_ops
from app.tasks.alembic_ops import (
    decrypt_execution_request_leaves,
    encrypt_execution_request_leaves,
)
from tests.app.conftest import postgres_worker_schema
from tests.app.encryption_fixtures import foreign_token
from tests.app.tasks.conftest import (
    EXECUTION_REQUEST_ARGS,
    EXECUTION_REQUEST_CONFIG,
    EXECUTION_REQUEST_PAYLOAD,
    request_document,
)

_REVISION = "f3b71c0d9a45"
_PRE_REVISION = "c4b8e1f7a2d9"

#: Column types are spelled out rather than left as ``String`` because
#: PostgreSQL will not implicitly cast a varchar into a ``json`` or
#: ``timestamptz`` column, while SQLite accepts anything, so a loose
#: declaration passes the SQLite legs and fails only on the deployment dialect.
_HISTORY = sa.table(
    "taskhistory",
    sa.column("id", sa.Integer),
    sa.column("task_id", sa.Integer),
    sa.column("status", sa.String),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
    sa.column("execution_request", AutoJSON),
)

_TASK = sa.table(
    "task",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("data", AutoJSON),
    sa.column("backend", sa.String),
    sa.column("owner", sa.String),
    sa.column("is_template", sa.Boolean),
    sa.column("protected", sa.Boolean),
    sa.column("alert_on_fail", sa.Boolean),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)


def seed_task(conn: Connection) -> None:
    """Insert the parent ``task`` row the history rows reference.

    :param conn: The connection to write through.
    """
    conn.execute(
        _TASK.insert().values(
            id=1,
            name="run-python",
            data={"task": "wrapped"},
            backend="PROXY",
            owner="ANY",
            is_template=False,
            protected=False,
            alert_on_fail=False,
            created_at=_TIMESTAMP,
            updated_at=_TIMESTAMP,
        )
    )


def seed_history(conn: Connection, history_id: int, document: Any) -> None:
    """Insert a ``taskhistory`` row carrying ``document`` verbatim.

    :param conn: The connection to write through.
    :param history_id: The primary key to assign.
    :param document: The exact ``execution_request`` value to store.
    """
    conn.execute(
        _HISTORY.insert().values(
            id=history_id,
            task_id=1,
            status="PENDING",
            created_at=_TIMESTAMP,
            updated_at=_TIMESTAMP,
            execution_request=document,
        )
    )


def stored_request(conn: Connection, history_id: int) -> Any:
    """Return a row's ``execution_request`` exactly as it is stored.

    :param conn: The connection to read through.
    :param history_id: The row to read.
    :return: The stored value, undecrypted.
    """
    return conn.execute(
        sa.select(_HISTORY.c.execution_request).where(_HISTORY.c.id == history_id)
    ).scalar_one()


class TestEncryptExecutionRequestLeavesMigration:
    """Cover the Alembic legs on the Tasks track's SQLite fixture."""

    @staticmethod
    def _seeded(cfg, sync_url: str, rows: dict[int, Any]) -> None:
        """Bring the schema to the pre-revision and insert ``rows``.

        :param cfg: The Alembic config the fixture built.
        :param sync_url: The synchronous URL of the fixture database.
        :param rows: The ``execution_request`` value to store per row id.
        """
        command.upgrade(cfg, _PRE_REVISION)
        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                seed_task(conn)
                for history_id, document in rows.items():
                    seed_history(conn, history_id, document)
        finally:
            engine.dispose()

    @staticmethod
    def _read(sync_url: str, history_id: int) -> Any:
        """Return one row's stored ``execution_request``.

        :param sync_url: The synchronous URL of the fixture database.
        :param history_id: The row to read.
        :return: The stored value, undecrypted.
        """
        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                return stored_request(conn, history_id)
        finally:
            engine.dispose()

    def test_upgrade_encrypts_every_protected_leaf(self, tasks_alembic_config):
        """Assert a plaintext row reaches the new revision with each leaf encrypted.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        """
        cfg, sync_url = tasks_alembic_config
        self._seeded(cfg, sync_url, {1: request_document()})

        command.upgrade(cfg, _REVISION)

        stored = self._read(sync_url, 1)
        assert json.loads(decrypt(stored["meta"]["args"])) == EXECUTION_REQUEST_ARGS
        assert json.loads(decrypt(stored["meta"]["config"])) == EXECUTION_REQUEST_CONFIG
        assert json.loads(decrypt(stored["payload"])) == EXECUTION_REQUEST_PAYLOAD
        assert stored["meta"]["_service_name"] == "mysql-1"
        assert stored["task"] == "run-python"

    def test_upgrade_leaves_an_already_encrypted_leaf_byte_identical(
        self, tasks_alembic_config
    ):
        """Assert a re-run rewrites nothing, including a foreign key's ciphertext.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        """
        cfg, sync_url = tasks_alembic_config
        mine = encrypt(json.dumps(EXECUTION_REQUEST_ARGS))
        theirs = foreign_token()
        self._seeded(cfg, sync_url, {1: request_document(args=mine, payload=theirs)})

        command.upgrade(cfg, _REVISION)

        stored = self._read(sync_url, 1)
        assert stored["meta"]["args"] == mine
        assert stored["payload"] == theirs

    def test_upgrade_skips_a_request_that_is_not_a_json_object(
        self, tasks_alembic_config
    ):
        """Assert a malformed row is left alone and does not abort the upgrade.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        """
        cfg, sync_url = tasks_alembic_config
        self._seeded(cfg, sync_url, {1: "not-a-document", 2: request_document()})

        command.upgrade(cfg, _REVISION)

        assert self._read(sync_url, 1) == "not-a-document"
        assert is_encrypted(self._read(sync_url, 2)["payload"])

    def test_downgrade_restores_plaintext(self, tasks_alembic_config):
        """Assert the rollback leaves the row as the previous release reads it.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        """
        cfg, sync_url = tasks_alembic_config
        self._seeded(cfg, sync_url, {1: request_document()})
        command.upgrade(cfg, _REVISION)

        command.downgrade(cfg, _PRE_REVISION)

        assert self._read(sync_url, 1) == request_document()

    def test_upgrade_rewrites_past_the_first_batch(
        self, tasks_alembic_config, monkeypatch: pytest.MonkeyPatch
    ):
        """Assert every row is rewritten when the table exceeds one read batch.

        The rewrite pages by primary key rather than selecting the whole table,
        so a bug in the cursor would leave everything after the first batch in
        the clear, which a single-batch fixture cannot show.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        :param monkeypatch: Used to shrink the batch below the seeded row count.
        """
        monkeypatch.setattr(alembic_ops, "_BATCH_SIZE", 2)
        row_count = 5
        cfg, sync_url = tasks_alembic_config
        self._seeded(
            cfg,
            sync_url,
            {index: request_document() for index in range(1, row_count + 1)},
        )

        command.upgrade(cfg, _REVISION)

        for index in range(1, row_count + 1):
            stored = self._read(sync_url, index)
            assert is_encrypted(stored["payload"]), f"row {index} left in the clear"
            assert is_encrypted(stored["meta"]["args"])

    def test_downgrade_completes_over_an_undecryptable_leaf(self, tasks_alembic_config):
        """Assert a leaf this key cannot read is left in place, not raised on.

        :param tasks_alembic_config: The Alembic config and URL fixture.
        """
        cfg, sync_url = tasks_alembic_config
        theirs = foreign_token()
        self._seeded(cfg, sync_url, {1: request_document(payload=theirs)})
        command.upgrade(cfg, _REVISION)

        command.downgrade(cfg, _PRE_REVISION)

        stored = self._read(sync_url, 1)
        assert stored["payload"] == theirs
        assert stored["meta"]["args"] == EXECUTION_REQUEST_ARGS


class TestExecutionRequestRewriteRealPostgres:
    """Exercise the rewrite on a real PostgreSQL engine, where the column is ``jsonb``.

    The Alembic legs above run on SQLite, so the bind and result processing the
    rewrite actually depends on in production is never touched there. Rendering
    the statement cannot substitute: the operation is the JSONB round trip.
    """

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_round_trip_rewrites_only_what_it_should(
        self, postgres_engine: AsyncEngine
    ) -> None:
        """Assert upgrade, re-run and downgrade behave on ``jsonb`` as on SQLite.

        :param postgres_engine: The real-PostgreSQL engine to run against.
        """
        plaintext = request_document()
        theirs = foreign_token()
        async with postgres_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            # The migration names its table unqualified, as a revision must, so
            # the worker schema has to reach it through search_path rather than
            # through the fixture's schema_translate_map.
            await conn.exec_driver_sql(
                f'SET LOCAL search_path TO "{postgres_worker_schema()}"'
            )
            await conn.run_sync(seed_task)
            await conn.run_sync(seed_history, 1, plaintext)
            await conn.run_sync(seed_history, 2, request_document(payload=theirs))
            await conn.run_sync(seed_history, 3, "not-a-document")

            await conn.run_sync(encrypt_execution_request_leaves)
            first = await conn.run_sync(stored_request, 1)
            assert is_encrypted(first["meta"]["args"])
            assert is_encrypted(first["payload"])
            assert await conn.run_sync(stored_request, 3) == "not-a-document"

            await conn.run_sync(encrypt_execution_request_leaves)
            assert await conn.run_sync(stored_request, 1) == first

            await conn.run_sync(decrypt_execution_request_leaves)
            assert await conn.run_sync(stored_request, 1) == plaintext
            assert (await conn.run_sync(stored_request, 2))["payload"] == theirs

            await conn.run_sync(SQLModel.metadata.drop_all)
