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

"""Tests for the alters legacy form reconstructor."""

import logging
from types import SimpleNamespace

from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.form_backfill import (
    FORM_BACKFILL_ENTRIES,
    reconstruct_alters_form,
)
from app.sep.apps.alters.models import AltersCreate
from app.sep.apps.framework.form_backfill import (
    _backfill_single_task,
    FormBackfillContext,
)
from app.sep.apps.framework.form_backfill_inventory import ServiceIdLookup
from app.sep.apps.framework.spec import RESERVED_FORM_KEY
from app.tasks.models import Task, TaskBackendEnum

EXPECTED_SERVICE_ID = 7


def _service(service_id: int, *, name: str, address: str, port: int) -> SimpleNamespace:
    """Build a minimal inventory MySQL service record for lookup tests."""
    return SimpleNamespace(
        id=service_id,
        type=ServiceTypeEnum.MYSQL,
        name=name,
        port=port,
        node=SimpleNamespace(address=address),
    )


def _lookup(*services: SimpleNamespace) -> ServiceIdLookup:
    """Build a lookup table from the supplied service records."""
    return ServiceIdLookup.from_services(services)


def _ctx(lookup: ServiceIdLookup) -> FormBackfillContext:
    """Return a backfill context wired to ``lookup``."""
    return FormBackfillContext(log=logging.getLogger("test"), service_lookup=lookup)


def _legacy_alters_task(
    *,
    name: str = "alter-legacy",
    target: str = "executor-1",
    schema_name: str = "app",
    table_name: str = "users",
    service_host: str = "db.internal",
    service_port: int = DEFAULT_MYSQL_PORT,
    service_name: str = "mysql-prod",
    parent: str | None = None,
    task: str = "run-command",
    alert_on_fail: bool = False,
) -> Task:
    """Build a legacy alters task row without ``data['_form']``."""
    data: dict = {
        "task": task,
        "meta": {
            "command": "pt-online-schema-change",
            "args": (
                "'--alter=ADD COLUMN c INT' --recursion-method=processlist --execute"
            ),
            "target": target,
            "_schema_name": schema_name,
            "_table_name": table_name,
            "_service_host": service_host,
            "_service_port": service_port,
            "_service_name": service_name,
        },
    }
    if parent is not None:
        data["parent"] = parent
    return Task(
        name=name,
        data=data,
        backend=TaskBackendEnum.PROXY,
        owner="ALTERS",
        alert_on_fail=alert_on_fail,
    )


class TestReconstructAltersForm:
    """Tests for ``reconstruct_alters_form``."""

    def test_happy_path(self):
        """Rebuild a create body from the parent task's meta and pt-osc args."""
        lookup = _lookup(
            _service(
                EXPECTED_SERVICE_ID,
                name="mysql-prod",
                address="db.internal",
                port=DEFAULT_MYSQL_PORT,
            )
        )
        task = _legacy_alters_task(alert_on_fail=True)

        body = reconstruct_alters_form(task, _ctx(lookup))

        assert body is not None
        assert body["task_name"] == "alter-legacy"
        assert body["hostname"] == "executor-1"
        assert body["service_id"] == EXPECTED_SERVICE_ID
        assert body["db_schema"] == "app"
        assert body["db_table"] == "users"
        assert body["alter"] == "ADD COLUMN c INT"
        assert body["recursion_method"] == "processlist"
        assert body["alert_on_fail"] is True
        AltersCreate.model_validate(body)

    def test_skips_satellite_tasks(self):
        """Skip satellite (dry-run / pre-checks) tasks that carry a ``parent`` link."""
        lookup = _lookup(
            _service(
                1, name="mysql-prod", address="db.internal", port=DEFAULT_MYSQL_PORT
            )
        )
        task = _legacy_alters_task(name="alter-legacy-dry-run", parent="alter-legacy")

        assert reconstruct_alters_form(task, _ctx(lookup)) is None

    def test_returns_none_without_schema_or_table(self):
        """Skip tasks whose meta omits the resolved schema/table names."""
        lookup = _lookup(
            _service(
                1, name="mysql-prod", address="db.internal", port=DEFAULT_MYSQL_PORT
            )
        )
        task = _legacy_alters_task()
        del task.data["meta"]["_table_name"]

        assert reconstruct_alters_form(task, _ctx(lookup)) is None

    def test_returns_none_when_service_unresolved(self):
        """Skip tasks whose database host cannot be matched in inventory."""
        lookup = _lookup(
            _service(
                1, name="mysql-prod", address="db.internal", port=DEFAULT_MYSQL_PORT
            )
        )
        task = _legacy_alters_task(
            service_host="10.0.0.9", service_name="unknown-service"
        )

        assert reconstruct_alters_form(task, _ctx(lookup)) is None

    def test_returns_none_when_not_run_command(self):
        """Skip tasks that are not ``run-command`` alters rows."""
        lookup = _lookup(
            _service(
                1, name="mysql-prod", address="db.internal", port=DEFAULT_MYSQL_PORT
            )
        )
        task = _legacy_alters_task(task="run-python")

        assert reconstruct_alters_form(task, _ctx(lookup)) is None


class TestBackfillSingleTask:
    """Tests for the orchestrator pipeline over alters tasks."""

    def test_stamps_alters_form(self):
        """Run the orchestrator pipeline for a reconstructable alters task."""
        lookup = _lookup(
            _service(
                EXPECTED_SERVICE_ID,
                name="mysql-prod",
                address="db.internal",
                port=DEFAULT_MYSQL_PORT,
            )
        )
        task = _legacy_alters_task(name="alter-stamp")
        entry = FORM_BACKFILL_ENTRIES[0]

        outcome = _backfill_single_task(task, entry, _ctx(lookup))

        assert outcome.label == "stamped"
        assert outcome.stamped_data is not None
        stamped_form = outcome.stamped_data[RESERVED_FORM_KEY]
        assert stamped_form["task_name"] == "alter-stamp"
        assert stamped_form["service_id"] == EXPECTED_SERVICE_ID
        assert stamped_form["db_schema"] == "app"
        assert stamped_form["db_table"] == "users"
