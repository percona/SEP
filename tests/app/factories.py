"""Define reusable model factories for tests."""

from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
from app.models import CasdoorUser
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import GeneratedTask, Task, TaskBackendEnum, TaskOwner


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
    owner: TaskOwner = TaskOwner.ALTERS
    backend: TaskBackendEnum = TaskBackendEnum.NOMAD


class PeriodicTaskFactory(SQLAlchemyFactory[PeriodicTask]):
    """Define factory for PeriodicTasks instances."""


class GeneratedTaskFactory(ModelFactory[GeneratedTask]):
    """Define factory for GenerateTask instances."""


class AltersCreateFactory(ModelFactory[AltersCreate]):
    """Define factory for AltersCreate instances."""


class CreatedNodeFactory(ModelFactory[CreatedNode]):
    """Define factory for CreatedNode instances."""


class CreatedServiceFactory(ModelFactory[CreatedService]):
    """Define factory for CreatedService instances."""


class CreatedSchemaFactory(ModelFactory[CreatedSchema]):
    """Define factory for CreatedSchema instances."""
