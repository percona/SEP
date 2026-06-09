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

"""Define reusable model factories for tests."""

from datetime import datetime, UTC

from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
from app.inventory.models import (
    HostSystemObservationWrite,
    NodeWrite,
    SchemaWrite,
    ServiceSystemObservationWrite,
    ServiceWrite,
    TableWrite,
)
from app.models import CasdoorUser
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.plugins.alters.models import AltersCreate
from app.sep.plugins.archives.models import ArchivesCreate
from app.tasks.models import Task, TaskBackendEnum, TaskWrite

MOCK_CREATED_NODE_ID = 1
MOCK_CREATED_SERVICE_ID = 1
MOCK_CREATED_SCHEMA_ID = 1
MOCK_CREATED_TABLE_ID = 1
MOCK_DESTINATION_TABLE_ID = 2
MOCK_OBSERVED_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)


class CasdoorSDKFactory(ModelFactory[CasdoorSDK]):
    """Define factory for CasdoorSDK instances."""


class OAuthTokenFactory(ModelFactory[OAuthToken]):
    """Define factory for OAuthToken instances."""


class CasdoorUserFactory(ModelFactory[CasdoorUser]):
    """Define factory for CasdoorUser instances."""

    is_forbidden: bool = False
    is_deleted: bool = False


class TaskFactory(ModelFactory[Task]):
    """Define factory for Task instances."""

    is_template: bool = False
    protected: bool = False
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD


class PeriodicTaskFactory(SQLAlchemyFactory[PeriodicTask]):
    """Define factory for PeriodicTasks instances."""


class GeneratedTaskFactory(ModelFactory[TaskWrite]):
    """Define factory for GenerateTask instances."""


class AltersCreateFactory(ModelFactory[AltersCreate]):
    """Define factory for AltersCreate instances."""

    schema_id = 1
    table_id = 2
    schema_name = ""
    table_name = ""
    recursion_method = "processlist"
    dsn_table = ""
    continue_on_pre_check_failure = False


class ArchivesCreateFactory(ModelFactory[ArchivesCreate]):
    """Define factory for ArchivesCreate instances."""


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
