"""Define reusable model factories for tests."""

from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
from app.inventory.models import NodeWrite, SchemaWrite, ServiceWrite, TableWrite
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
