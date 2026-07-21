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

"""Derive the AppSchema for the backup_mongo plugin model-first.

The schema is derived from the model-first
:class:`~app.sep.apps.backup_mongo.models.BackupForm` plus the
:data:`~app.sep.apps.backup_mongo.views.backup_mongo_views` presentation
bundle. :data:`BACKUP_MONGO_DERIVED` carries the three ``DerivedTask`` specs (with
their two-step ``payload_substitutions``) into the ``derived`` block of
``GET /schema``; the cascade create route reuses the same specs to POST the
logical, physical, and status siblings. The Task-section description is built
from those specs so the user-facing copy cannot drift from ``name_suffix``.
"""

from collections.abc import Sequence
from dataclasses import replace

from app.sep.apps.backup_mongo.models import BackupForm, BackupType
from app.sep.apps.backup_mongo.views import backup_mongo_views
from app.sep.apps.framework.form_dsl import derive_app_schema, TASK_SECTION_LAYOUT
from app.sep.apps.framework.schema import DerivedTask, RelatedApp

BACKUP_MONGO_DERIVED = [
    DerivedTask(
        name_suffix="-logical",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
        },
        data_overrides={"backup_type": BackupType.PBM_LOGICAL.value},
    ),
    DerivedTask(
        name_suffix="-physical",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
            BackupType.PBM_LOGICAL.value: BackupType.PBM_PHYSICAL.value,
        },
        data_overrides={"backup_type": BackupType.PBM_PHYSICAL.value},
    ),
    DerivedTask(
        name_suffix="-status",
        payload_substitutions={
            BackupType.PBM_CONFIG.value: BackupType.PBM_LOGICAL.value,
            BackupType.PBM_LOGICAL.value: BackupType.PBM_STATUS.value,
        },
        data_overrides={"backup_type": BackupType.PBM_STATUS.value},
    ),
]


def _format_english_list(items: Sequence[str]) -> str:
    """Join ``items`` with commas and a final ``and`` (Oxford comma when ≥3)."""
    match list(items):
        case []:
            raise ValueError("expected at least one item")
        case [only]:
            return only
        case [first, second]:
            return f"{first} and {second}"
        case [*leading, last]:
            return f"{', '.join(leading)}, and {last}"


def _derived_sibling_task_description(specs: Sequence[DerivedTask]) -> str:
    """Build the Task-section note from ``DerivedTask.name_suffix`` values.

    Derived-task fan-out only (not field-level host cascading).
    """
    labels = [spec.name_suffix.removeprefix("-") for spec in specs]
    count = len(labels)
    noun = "sibling task" if count == 1 else "sibling tasks"
    # Prefer short English counts for the common cascade sizes.
    count_word = {1: "one", 2: "two", 3: "three"}.get(count, str(count))
    return (
        f"Creating this backup produces {count_word} {noun}: "
        f"{_format_english_list(labels)}."
    )


#: Task section description overlays the shared layout; sourced from
#: :data:`BACKUP_MONGO_DERIVED` so suffix changes stay in the UI copy.
_BACKUP_MONGO_LAYOUT = replace(
    backup_mongo_views.layout,
    sections=tuple(
        replace(
            section,
            description=_derived_sibling_task_description(BACKUP_MONGO_DERIVED),
        )
        if section.key == TASK_SECTION_LAYOUT.key
        else section
        for section in backup_mongo_views.layout.sections
    ),
)

backup_mongo_schema = derive_app_schema(
    BackupForm,
    _BACKUP_MONGO_LAYOUT,
    name="backup_mongo",
    display_name="MongoDB Backups",
    description=(
        "Configure Percona Backup for MongoDB (PBM) and manage logical, "
        "physical, and status backup tasks."
    ),
    capabilities=backup_mongo_views.capabilities,
    list_view=backup_mongo_views.list_view,
    detail_view=backup_mongo_views.detail_view,
    derived=BACKUP_MONGO_DERIVED,
    related_apps=[
        RelatedApp(
            app_key="backup_mongo/restore",
            label="Restore",
            route_segment="restores",
        ),
    ],
)
