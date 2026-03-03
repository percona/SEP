# Copyright 2026 Percona LLC
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

from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
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


class ArchivesCreateFactory(ModelFactory[ArchivesCreate]):
    """Define factory for ArchivesCreate instances."""


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
