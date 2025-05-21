"""Define settings for periodic tasks in the Tasks app."""

from enum import auto, StrEnum
from typing import ClassVar

from app.core.config import BaseYamlSettings
from app.core.utils.fields import EnumFieldMixin
from app.tasks.models import TaskOwner


class PeriodicTaskAction(EnumFieldMixin, StrEnum):
    """Control the choice of actions to perform to expired and orphaned periodic tasks.

    :cvar NOTHING: Do nothing.
    :vartype NOTHING: str
    :cvar DISABLE: Disable the matching periodic tasks.
    :vartype DISABLE: str
    :cvar DELETE: Delete the matching periodic tasks.
    :vartype DELETE: str
    """

    NOTHING = auto()
    DISABLE = auto()
    DELETE = auto()


class PeriodicTasksSettings(BaseYamlSettings):
    """Define settings for tasks configuration.

    :cvar SETTINGS_PREFIXES: The prefixes for periodic tasks related settings in the
        configuration file. Set to `["TASKS", "PERIODIC"]`.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param AVAILABLE_TO_OWNERS: The task owners for which the periodic tasks feature
        will be available. Defaults to {TaskOwner.ARCHIVER}.
    :type AVAILABLE_TO_OWNERS: set[TaskOwner]
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS", "PERIODIC"]
    AVAILABLE_TO_OWNERS: set[TaskOwner] = [TaskOwner.ARCHIVER]


periodic_tasks_settings = PeriodicTasksSettings()
