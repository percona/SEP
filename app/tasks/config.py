"""Define settings for the Tasks app."""

from collections import defaultdict
from datetime import timedelta
from typing import ClassVar

from pydantic import Field, field_validator

from app.core.config import BaseYamlAppSettings
from app.core.db.config import DatabaseOptions
from app.core.middleware.security_headers import SecurityHeadersOptions
from app.tasks.anonymizer import AnonymizerEntity
from app.tasks.execution.executors.nomad import NomadExecutor
from app.tasks.models import TaskOwner


class TasksSettings(BaseYamlAppSettings):
    """Define settings for tasks configuration.

    :cvar SETTINGS_PREFIXES: The prefixes for task-related settings in the
        configuration file.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param UVICORN_PORT: The port to be used by Uvicorn for running the server.
        Defaults to 8002.
    :type UVICORN_PORT: int
    :param NOMAD: The configuration options for integrating with Nomad.
    :type NOMAD: NomadOptions
    :param DATABASE: The database configuration options. Defaults to an SQLite database
        with the name 'tasks.db'.
    :type DATABASE: DatabaseOptions
    :param SECURITY_HEADERS: Specific options for the SecurityHeadersMiddleware.
        Use `False` to disable the middleware completely.
    :type SECURITY_HEADERS: SecurityHeadersOptions | None
    :param SYNC_LOCK_TTL: The timeout for the TaskHistory sync lock. Defaults to 5
        minutes.
    :type SYNC_LOCK_TTL: timedelta
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS"]
    UVICORN_PORT: int = 8002
    NOMAD: NomadExecutor
    DATABASE: DatabaseOptions = DatabaseOptions(NAME="tasks.db")
    SECURITY_HEADERS: SecurityHeadersOptions | None = SecurityHeadersOptions(
        content_security_policy_strict=False
    )
    SYNC_LOCK_TTL: timedelta = timedelta(minutes=5)
    MASKING_ENTITIES: defaultdict[TaskOwner, set[AnonymizerEntity]] = Field(
        default_factory=dict
    )

    @field_validator("MASKING_ENTITIES", mode="before")
    @classmethod
    def _wrap_defaultdict(
        cls, v: dict
    ) -> defaultdict[TaskOwner, set[AnonymizerEntity]]:
        """Convert and validate the masking entities configuration.

        Transform the input dictionary of owner names and entity names into a
        defaultdict mapping TaskOwner enums to sets of AnonymizerEntity enums.
        If no configuration is provided, returns a defaultdict that defaults to
        an empty set of AnonymizerEntity.

        :param v: The input dictionary mapping owner names to lists of entity names.
        :type v: dict
        :return: A defaultdict mapping TaskOwner enums to sets of AnonymizerEntity enums.
        :rtype: defaultdict[TaskOwner, set[AnonymizerEntity]]
        """
        converted: dict[TaskOwner, set[AnonymizerEntity]] = {}
        if v:
            for owner_name, entity_names in v.items():
                owner = TaskOwner[owner_name]
                converted[owner] = {AnonymizerEntity[e] for e in entity_names}

        return defaultdict(lambda: set(AnonymizerEntity), converted)


tasks_settings = TasksSettings()
