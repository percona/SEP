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

"""Define reusable model factories for tests.

Core, cross-app factories only. A factory for an activatable app's model belongs
in ``tests/app/sep/apps/<app>/factories.py``, beside that app's tests.
"""

from datetime import datetime, UTC

from polyfactory import Use
from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.auth.providers.casdoor.sdk import CasdoorSDK
from app.core.auth.providers.grafana.models import GrafanaUser
from app.inventory.models import (
    HostSystemObservationWrite,
    NodeWrite,
    SchemaWrite,
    ServiceSystemObservationWrite,
    ServiceWrite,
    TableWrite,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskExecutionRequest,
    TaskHistory,
    TaskHistoryResponse,
    TaskHistoryStatusEnum,
    TaskResponse,
    TaskWrite,
)

MOCK_CREATED_NODE_ID = 1
MOCK_CREATED_SERVICE_ID = 1
MOCK_CREATED_SCHEMA_ID = 1
MOCK_CREATED_TABLE_ID = 1
MOCK_DESTINATION_TABLE_ID = 2
MOCK_OBSERVED_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


def build_task_history(
    task: Task, status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.SUCCESS
) -> TaskHistory:
    """Build an unsaved ``TaskHistory`` for ``task`` with an execution request.

    ``execution_request.task`` mirrors ``task.name`` so JSON-extraction tests can
    assert the stored scalar round-trips. Callers persist it via
    ``TaskHistoryManager.save``.

    :param task: Provide the task that owns the history record.
    :param status: Set the execution status for the created history record.
    :return: Return an unsaved task history model.
    """
    return TaskHistory(
        task_id=task.id,
        task=task,
        execution_request=TaskExecutionRequest(
            task=task.name,
            target="node1",
            meta={"target": "node1"},
            tracking={"evaluation_id": "", "allocation_id": None},
        ),
        status=status,
        executed_by="test-user",
    )


class CasdoorSDKFactory(ModelFactory[CasdoorSDK]):
    """Define factory for CasdoorSDK instances."""


class OAuthTokenFactory(ModelFactory[OAuthToken]):
    """Define factory for OAuthToken instances."""


class CasdoorUserFactory(ModelFactory[CasdoorUser]):
    """Define factory for CasdoorUser instances."""

    is_forbidden: bool = False
    is_deleted: bool = False


class GrafanaUserFactory(ModelFactory[GrafanaUser]):
    """Define factory for GrafanaUser instances."""


class TaskFactory(ModelFactory[Task]):
    """Define factory for Task instances.

    Pins the hook-path fields to None so the random strings polyfactory would
    otherwise generate for them do not trip the ``TaskWrite`` allow-list
    validator wherever a built task is revalidated as a write.
    """

    is_template: bool = False
    protected: bool = False
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD
    alert_detail_builder = None
    run_result_recorder = None


class PeriodicTaskFactory(SQLAlchemyFactory[PeriodicTask]):
    """Define factory for PeriodicTasks instances."""


class GeneratedTaskFactory(ModelFactory[TaskWrite]):
    """Define factory for TaskWrite instances.

    Pins the hook-path fields to None so factory-generated values do not trip
    the ``TaskWrite`` allow-list validator.
    """

    alert_detail_builder = None
    run_result_recorder = None


class TaskResponseFactory(ModelFactory[TaskResponse]):
    """Define factory for TaskResponse instances.

    Pins ``backend`` to Nomad so the ``TaskBase`` proxy-backend validator (which
    requires a ``data["task"]`` key) does not reject factory-generated data, and
    the hook-path fields to None so they do not trip the ``TaskWrite``
    allow-list validator wherever a built response is revalidated as a write.
    """

    backend: TaskBackendEnum = TaskBackendEnum.NOMAD
    is_template: bool = False
    protected: bool = False
    deleted_at = None
    created_by = None
    last_updated_by = None
    alert_detail_builder = None
    run_result_recorder = None


class TaskHistoryResponseFactory(ModelFactory[TaskHistoryResponse]):
    """Define factory for TaskHistoryResponse instances.

    Builds the wire shape the Tasks API returns from ``/{name}/history/`` and
    ``/execute/{name}``. ``status`` defaults to ``SUCCESS`` and is overridable so
    history fixtures can seed any execution state.
    """

    status: TaskHistoryStatusEnum = TaskHistoryStatusEnum.SUCCESS
    has_logs: bool = False
    started_at = None
    finished_at = None
    anonymize_mask = None
    executed_by = None
    task = Use(TaskResponseFactory.build)


class NodeWriteFactory(ModelFactory[NodeWrite]):
    """Define factory for NodeWrite instances."""

    source = None
    external_id = None


class ServiceWriteFactory(ModelFactory[ServiceWrite]):
    """Define factory for ServiceWrite instances."""

    node_id = None
    external_id = None


class SchemaWriteFactory(ModelFactory[SchemaWrite]):
    """Define factory for SchemaWrite instances."""

    service_id = None


class TableWriteFactory(ModelFactory[TableWrite]):
    """Define factory for TableWrite instances."""

    schema_id = None


class HostSystemObservationWriteFactory(ModelFactory[HostSystemObservationWrite]):
    """Define factory for HostSystemObservationWrite instances."""

    node_id = None
    os_version = "Ubuntu 22.04"
    installed_packages = [{"name": "mysql-client", "version": "8.0.35"}]
    config = {"kernel": "5.15.0"}
    observed_at = MOCK_OBSERVED_AT


class ServiceSystemObservationWriteFactory(ModelFactory[ServiceSystemObservationWrite]):
    """Define factory for ServiceSystemObservationWrite instances."""

    service_id = None
    db_engine_version = "8.0.35"
    observed_at = MOCK_OBSERVED_AT


class CreatedNodeFactory(ModelFactory[CreatedNode]):
    """Define factory for CreatedNode instances."""

    id = MOCK_CREATED_NODE_ID


class CreatedServiceFactory(ModelFactory[CreatedService]):
    """Define factory for CreatedService instances."""

    id = MOCK_CREATED_SERVICE_ID


class CreatedSchemaFactory(ModelFactory[CreatedSchema]):
    """Define factory for CreatedSchema instances."""

    id = MOCK_CREATED_SCHEMA_ID
    service_id: int = MOCK_CREATED_SERVICE_ID


class CreatedTableFactory(ModelFactory[CreatedTable]):
    """Define factory for CreatedTable instances."""

    id = MOCK_CREATED_TABLE_ID
    schema_id: int = MOCK_CREATED_SCHEMA_ID
