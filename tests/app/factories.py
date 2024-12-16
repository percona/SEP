"""Define reusable model factories for tests."""

from polyfactory.factories.pydantic_factory import ModelFactory
from polyfactory.factories.sqlalchemy_factory import SQLAlchemyFactory
from sqlalchemy_celery_beat import PeriodicTask

from app.core.auth.models import OAuthToken
from app.core.auth.providers.casdoor import CasdoorSDK
from app.models import CasdoorUser
from app.tasks.models import Task


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


class PeriodicTaskFactory(SQLAlchemyFactory[PeriodicTask]):
    """Define factory for PeriodicTasks instances."""
