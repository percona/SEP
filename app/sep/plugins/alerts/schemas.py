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

"""Define Pydantic request and response models for the alerts plugin JSON API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.utils.fields import NonEmptyStr


class PushRequest(BaseModel):
    """Describe the request body for ``POST /api/plugins/alerts/push``.

    :param selected_templates: Names of templates to push to PMM. Must be a
        non-empty list of non-empty strings.
    :type selected_templates: list[NonEmptyStr]
    """

    selected_templates: list[NonEmptyStr] = Field(min_length=1)


class PushItemResult(BaseModel):
    """Represent a per-template result row returned by the push endpoint.

    :param name: The template name the result applies to.
    :type name: str
    :param status: One of ``"success"``, ``"skipped"``, ``"error"``.
    :type status: Literal["success", "skipped", "error"]
    :param message: A human-readable description of the outcome.
    :type message: str
    """

    name: str
    status: Literal["success", "skipped", "error"]
    message: str


class PushResponse(BaseModel):
    """Wrap the per-template results returned by the push endpoint.

    :param results: One :class:`PushItemResult` per template in the request.
    :type results: list[PushItemResult]
    """

    results: list[PushItemResult]


class RestoreRequest(BaseModel):
    """Describe the request body for ``POST /api/plugins/alerts/restore``.

    :param backup_id: Primary key of the :class:`~app.sep.plugins.alerts.models.AlertBackup`
        row to restore from. Must be a positive integer.
    :type backup_id: int
    """

    backup_id: int = Field(gt=0)


class RestoreResponse(BaseModel):
    """Wrap the summary returned by the restore endpoint.

    :param status: ``"success"`` on a complete restore.
    :type status: Literal["success"]
    :param details: Per-section restore counts as returned by
        :func:`~app.sep.plugins.alerts.restore.restore_from_backup`.
    :type details: dict[str, Any]
    """

    status: Literal["success"]
    details: dict[str, Any]


class BackupSummary(BaseModel):
    """Represent a compact backup row used by the list endpoint.

    :param id: Primary key of the backup row.
    :type id: int
    :param created_at: UTC timestamp the backup was written.
    :type created_at: datetime
    :param metadata: Summary counts persisted alongside the backup snapshot.
    :type metadata: dict[str, Any]
    """

    id: int
    created_at: datetime
    metadata: dict[str, Any]


class BackupListResponse(BaseModel):
    """Wrap a list of backup summaries.

    :param items: Backups ordered by ``created_at`` descending.
    :type items: list[BackupSummary]
    """

    items: list[BackupSummary]


class BackupDetailTemplate(BaseModel):
    """Represent a template entry inside a backup snapshot.

    :param name: The template name.
    :type name: str
    :param summary: The template summary blurb.
    :type summary: str
    """

    name: str
    summary: str


class BackupDetailRule(BaseModel):
    """Represent a rule entry inside a backup snapshot.

    :param title: The rule title.
    :type title: str
    """

    title: str


class BackupDetailContactPoint(BaseModel):
    """Represent a contact-point entry inside a backup snapshot.

    :param name: The contact point name.
    :type name: str
    :param type: The contact point type (e.g. ``"pagerduty"``).
    :type type: str
    """

    name: str
    type: str


class BackupDetailFolder(BaseModel):
    """Represent a folder entry inside a backup snapshot.

    :param title: The folder title.
    :type title: str
    """

    title: str


class BackupDetail(BaseModel):
    """Describe the full detail response for a single backup.

    :param id: Primary key of the backup row.
    :type id: int
    :param created_at: UTC timestamp the backup was written.
    :type created_at: datetime
    :param templates: Templates captured in the backup.
    :type templates: list[BackupDetailTemplate]
    :param rules: Rules captured in the backup.
    :type rules: list[BackupDetailRule]
    :param contact_points: Contact points captured in the backup.
    :type contact_points: list[BackupDetailContactPoint]
    :param folders: Folders captured in the backup.
    :type folders: list[BackupDetailFolder]
    :param notification_policy_receiver: Top-level receiver from the captured
        notification policy, or ``None`` when no policy was captured.
    :type notification_policy_receiver: str | None
    """

    id: int
    created_at: datetime
    templates: list[BackupDetailTemplate]
    rules: list[BackupDetailRule]
    contact_points: list[BackupDetailContactPoint]
    folders: list[BackupDetailFolder]
    notification_policy_receiver: str | None


class PagerDutyRequest(BaseModel):
    """Describe the request body for ``POST /api/plugins/alerts/pagerduty``.

    :param integration_key: The PagerDuty integration key. Must be non-empty
        after stripping whitespace.
    :type integration_key: NonEmptyStr
    """

    integration_key: NonEmptyStr


class PagerDutyResponse(BaseModel):
    """Describe the response body for the PagerDuty save / delete endpoints.

    :param status: ``"created"``, ``"updated"`` (save) or ``"deleted"`` (delete).
    :type status: Literal["created", "updated", "deleted"]
    """

    status: Literal["created", "updated", "deleted"]
