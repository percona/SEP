"""Define the alert template loader for the alerts plugin."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

import yaml
from fastapi import Depends

from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

DEFAULT_DEFINITIONS_DIR = Path(__file__).parent / "alert_definitions"


@lru_cache
def load_alert_templates(
    definitions_dir: Path,
) -> dict[ServiceType, list[AlertTemplate]]:
    """Load and return alert templates grouped by service type from a directory.

    Read all ``*.yaml`` files in `definitions_dir`, validate each one as an
    `AlertTemplate`, and group the results by `ServiceType`. Every `ServiceType`
    is represented as a key in the returned mapping, even when no templates
    exist for that type.

    Results are cached per `definitions_dir` path via `lru_cache` so repeated
    calls with the same directory do not trigger additional disk reads.

    :param definitions_dir: Path to the directory containing YAML alert definition
        files.
    :type definitions_dir: Path
    :return: A mapping from each `ServiceType` to the list of `AlertTemplate`
        objects loaded for that type.
    :rtype: dict[ServiceType, list[AlertTemplate]]
    :raises pydantic.ValidationError: If any YAML file contains invalid data that
        does not satisfy the `AlertTemplate` schema.
    """
    templates: dict[ServiceType, list[AlertTemplate]] = {svc: [] for svc in ServiceType}
    for yaml_file in sorted(definitions_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        template = AlertTemplate.model_validate(data)
        templates[template.service_type].append(template)
    return templates


def get_alert_templates() -> dict[ServiceType, list[AlertTemplate]]:
    """Return alert templates loaded from the configured definitions directory.

    Use `sep_settings.ALERT_DEFINITIONS_DIR` when set, otherwise fall back to
    the bundled `alert_definitions/` directory alongside this module. This
    function is intended for use as a FastAPI dependency.

    :return: A mapping from each `ServiceType` to the list of `AlertTemplate`
        objects loaded for that type.
    :rtype: dict[ServiceType, list[AlertTemplate]]
    """
    from app.sep.config import sep_settings

    definitions_dir = sep_settings.ALERT_DEFINITIONS_DIR or DEFAULT_DEFINITIONS_DIR
    return load_alert_templates(definitions_dir)


AlertTemplatesDep = Annotated[
    dict[ServiceType, list[AlertTemplate]], Depends(get_alert_templates)
]
