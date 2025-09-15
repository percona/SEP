# Copyright (C) 2025 Percona LLC
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

"""Define settings for data anonymization in the tasks app."""

from collections import defaultdict
from typing import Any, ClassVar

from pydantic import Field, field_validator

from app.core.config import BaseYamlSettings
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.models import TaskOwner


class AnonymizerSettings(BaseYamlSettings):
    """Define settings for task data anonymization.

    :cvar SETTINGS_PREFIXES: The prefixes for anonymizer related settings in the
        configuration file. Set to `["TASKS", "ANONYMIZER"]`.
    :vartype SETTINGS_PREFIXES: ClassVar[list[str]]
    :param DEFAULT_ENTITIES: A mapping of task owners to sets of anonymizer entities.
        If set to `"*"`, defaults to all available anonymizer entities for all owners.
        If a list of anonymizer entities is provided, it will be used as default for all
        owners. Defaults to an empty set.
    :type DEFAULT_ENTITIES: defaultdict[TaskOwner, set[PIIEntity]]
    :param NLP_MODELS: A mapping of language codes to spaCy model names for NLP
        processing. Defaults to `{"en": "en_core_web_md"}`.
    :type NLP_MODELS: dict[str, str]
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TASKS", "ANONYMIZER"]
    DEFAULT_ENTITIES: defaultdict[TaskOwner, set[PIIEntity]] = Field(
        default_factory=dict, validate_default=True
    )
    NLP_MODELS: dict[str, str] = Field({"en": "en_core_web_md"}, min_length=1)

    @field_validator("DEFAULT_ENTITIES", mode="before")
    @classmethod
    def _validate_entities_defaultdict(cls, v: Any) -> Any:
        """Validate and transform the DEFAULT_ENTITIES field.

        :param v: The value to be validated.
        :type v: Any
        :return: A defaultdict with TaskOwner keys and sets of PIIEntity as
            values.
        :rtype: Any
        """
        if v == "*":
            v = list(PIIEntity)
        if isinstance(v, list):
            entities = set(v)
            return defaultdict(
                lambda: entities, {owner: entities for owner in TaskOwner}
            )
        if isinstance(v, dict):
            return defaultdict(set, v)

        return v

    @property
    def default_analyzer_language(self) -> str:
        """Get the default language code for the NLP models.

        :return: The first language code from the NLP_MODELS dictionary.
        :rtype: str
        """
        return next(iter(self.NLP_MODELS))


anonymizer_settings = AnonymizerSettings()
