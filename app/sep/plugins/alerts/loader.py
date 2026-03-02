"""Define the alert template loader for the alerts plugin."""

from functools import lru_cache
from pathlib import Path

import yaml

from app.sep.config import sep_settings
from app.sep.plugins.alerts.models import AlertTemplate, ServiceType

DEFAULT_DEFINITIONS_DIR = Path(__file__).parent / "alert_definitions"


@lru_cache
def load_alert_templates(
    definitions_dir: Path,
) -> dict[ServiceType, tuple[AlertTemplate, ...]]:
    """Load and return alert templates grouped by service type from a directory.

    Read all `*.yaml` files in `definitions_dir`, validate each one as an
    `AlertTemplate`, and group the results by `ServiceType`. Every `ServiceType`
    is represented as a key in the returned mapping, even when no templates
    exist for that type.

    Results are cached per `definitions_dir` path via `lru_cache` so repeated
    calls with the same directory do not trigger additional disk reads. The
    per-service-type sequences are tuples (immutable) to prevent callers from
    accidentally mutating the cached state.

    :param definitions_dir: Path to the directory containing YAML alert definition
        files. Must be an existing directory.
    :type definitions_dir: Path
    :return: A mapping from each `ServiceType` to a tuple of `AlertTemplate`
        objects loaded for that type.
    :rtype: dict[ServiceType, tuple[AlertTemplate, ...]]
    :raises NotADirectoryError: If `definitions_dir` does not exist or is not a
        directory.
    :raises TypeError: If a YAML file does not contain a mapping at its top level.
    :raises pydantic.ValidationError: If a YAML file contains a mapping that does
        not satisfy the `AlertTemplate` schema.
    """
    if not definitions_dir.is_dir():
        raise NotADirectoryError(
            f"Alert definitions directory does not exist or is not a directory: "
            f"{definitions_dir}"
        )
    result = {svc: [] for svc in ServiceType}
    for yaml_file in sorted(definitions_dir.glob("*.yaml")):
        data = yaml.safe_load(yaml_file.read_text())
        if not isinstance(data, dict):
            raise TypeError(
                f"Expected a YAML mapping in {yaml_file}, got "
                f"{type(data).__name__ if data is not None else 'empty file'}"
            )
        template = AlertTemplate.model_validate(data)
        result[template.service_type].append(template)
    return {svc: tuple(templates) for svc, templates in result.items()}


def get_alert_templates() -> dict[ServiceType, tuple[AlertTemplate, ...]]:
    """Return alert templates loaded from the configured definitions directory.

    Use `sep_settings.ALERT_DEFINITIONS_DIR` when set, otherwise fall back to
    the bundled `alert_definitions/` directory alongside this module. This
    function is intended for use as a FastAPI dependency.

    :return: A mapping from each `ServiceType` to a tuple of `AlertTemplate`
        objects loaded for that type.
    :rtype: dict[ServiceType, tuple[AlertTemplate, ...]]
    """
    definitions_dir = sep_settings.ALERT_DEFINITIONS_DIR or DEFAULT_DEFINITIONS_DIR
    return load_alert_templates(definitions_dir)
