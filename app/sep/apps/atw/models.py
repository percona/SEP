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

"""Define the ATW plugin's DB tables and their API request/response models.

This module is loaded by the Alembic plugin-discovery loader at migration time,
so it must stay self-contained — importing only from ``app.core``, ``pydantic``,
``sqlalchemy``, and ``sqlmodel``, never from sibling plugins or other service
packages (that would register foreign tables in ``SQLModel.metadata`` and leak
them into the ``sep`` autogenerate). The category taxonomy, which depends on
``app.inventory``, lives in :mod:`app.sep.apps.atw.categories`.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, UUID4
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlalchemy import Enum as EnumField
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db.models import BaseUUIDSQLModel, DateTimeWithTimezone
from app.core.utils.date_time import utc_now
from app.core.utils.fields import EnumFieldMixin, NonEmptyStr, UTCDatetime


def _default_incident_name() -> str:
    """Build the default incident name embedding the creation time.

    :return: A timestamped name of the form ``Incident YYYY-MM-DD HH:MM``.
    """
    return f"Incident {utc_now():%Y-%m-%d %H:%M}"


class AtwIncidentBase(SQLModel):
    """Define the incident fields shared by the create payload and the DB table.

    :param name: Human-readable incident label; defaults to a timestamped name.
    :param case_ref: Optional support-case reference.
    """

    name: NonEmptyStr = SQLField(default_factory=_default_incident_name)
    case_ref: str | None = SQLField(default=None)


class AtwIncident(BaseUUIDSQLModel, AtwIncidentBase, table=True):
    """Represent a named grouping of diagnostic snippet executions per support case.

    :param created_by: Username of the support engineer who created the incident.
    :param closed_at: When the incident was closed, if ever; ``None`` means open.
    :param executions: The snippet executions grouped under this incident.
    :param send_logs: The delivery attempts recorded against this incident.
    """

    __tablename__ = "atw_incident"

    created_by: str = SQLField(nullable=False)
    closed_at: UTCDatetime | None = SQLField(default=None, sa_type=DateTimeWithTimezone)
    executions: list["AtwIncidentExecution"] = Relationship(
        back_populates="incident",
        cascade_delete=True,
    )
    send_logs: list["AtwSendLog"] = Relationship(
        back_populates="incident",
        cascade_delete=True,
    )


class AtwIncidentWrite(AtwIncidentBase):
    """Define the create payload; ``name`` defaults and ``created_by`` is server-stamped."""


class AtwIncidentUpdate(SQLModel):
    """Define the PATCH payload — all fields optional; unset fields are untouched.

    :param name: New incident label. Non-nullable when provided: an omitted
        ``name`` is left unchanged, while an explicit null or empty string is
        rejected with 422 (the column is NOT NULL). Typing it as a non-optional
        ``NonEmptyStr`` with a ``None`` default keeps the omitted-field sentinel
        out of the JSON schema, so the generated client advertises ``name?: string``
        (not ``string | null``) — matching what the route actually accepts.
    :param case_ref: New support-case reference; an explicit null clears it.
    """

    name: NonEmptyStr = Field(default=None)
    case_ref: str | None = None


class AtwIncidentResponse(BaseModel):
    """Represent a persisted diagnostic incident.

    Every field is always present on a stored incident, so — unlike returning
    the :class:`AtwIncident` table model directly — the generated client types
    them as required rather than optional.

    :param id: The incident's UUID primary key.
    :param name: Human-readable incident label.
    :param case_ref: Support-case reference, if set.
    :param created_by: Username of the support engineer who created the incident.
    :param created_at: When the incident was created.
    :param updated_at: When the incident was last updated, if ever.
    :param closed_at: When the incident was closed, if ever; ``None`` means open.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    name: NonEmptyStr
    case_ref: str | None
    created_by: str
    created_at: UTCDatetime
    updated_at: UTCDatetime | None
    closed_at: UTCDatetime | None


class AtwIncidentExecution(BaseUUIDSQLModel, table=True):
    """Link one diagnostic snippet execution to its incident grouping.

    :param incident_id: Foreign key to the owning :class:`AtwIncident`.
    :param task_history_id: Logical reference to the tasks-service execution row.
    :param snippet_filename: Filename of the executed diagnostic snippet.
    :param incident: The incident this execution belongs to.
    """

    __tablename__ = "atw_incident_execution"
    __table_args__ = (
        UniqueConstraint(
            "incident_id",
            "task_history_id",
            name="uq_atw_incident_execution_incident_task",
        ),
    )

    incident_id: UUID4 = SQLField(
        foreign_key="atw_incident.id",
        ondelete="CASCADE",
    )
    task_history_id: int = SQLField(index=True)
    snippet_filename: str
    incident: AtwIncident = Relationship(back_populates="executions")


class AtwSendStatusEnum(EnumFieldMixin, StrEnum):
    """Enumerate the lifecycle of one diagnostics send attempt.

    The column stores member *names* (``PENDING``); the API serializes the
    ``StrEnum`` *values* (``pending``).
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

    @classmethod
    def active_statuses(cls) -> frozenset["AtwSendStatusEnum"]:
        """Return the statuses a send can still leave on its own.

        :return: The non-terminal statuses.
        """
        return frozenset({cls.PENDING, cls.RUNNING})

    def is_terminal(self) -> bool:
        """Return whether this status is a finished outcome.

        :return: ``True`` for a status no further transition leaves.
        """
        return self not in self.active_statuses()


class AtwSendLog(BaseUUIDSQLModel, table=True):
    """Record one attempt to deliver an incident's diagnostics to the receiver.

    The row *is* the job: the create endpoint writes it as ``PENDING`` and
    enqueues the Celery task with its id, and the status endpoint reads it back.
    Because the receiver's credentials can create attachments but not read them,
    ``detail`` carries the full final-upload response and is the only evidence a
    send ever landed.

    :param incident_id: Foreign key to the owning :class:`AtwIncident`.
    :param case_ref: The support-case reference this send targets, snapshotted at
        request time so a later edit of the incident does not rewrite history.
    :param requested_by: Username of the support engineer who started the send.
    :param status: The attempt's lifecycle status.
    :param started_at: When the worker picked the attempt up, if it did.
    :param finished_at: When the attempt reached a terminal status, if it did.
    :param detail: The attempt's recorded evidence -- selected executions, per-step
        outcomes, the full upload response, or the error that ended it.
    :param incident: The incident this attempt belongs to.
    """

    __tablename__ = "atw_send_log"

    incident_id: UUID4 = SQLField(
        foreign_key="atw_incident.id",
        ondelete="CASCADE",
        index=True,
    )
    case_ref: NonEmptyStr = SQLField(nullable=False)
    requested_by: str = SQLField(nullable=False)
    status: AtwSendStatusEnum = SQLField(
        default=AtwSendStatusEnum.PENDING,
        sa_column=Column(
            EnumField(AtwSendStatusEnum, native_enum=False, create_constraint=True),
            nullable=False,
        ),
    )
    started_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    finished_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    detail: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON))
    incident: AtwIncident = Relationship(back_populates="send_logs")


class AtwSendJobWrite(BaseModel):
    """Define the payload starting one diagnostics send.

    :param case_ref: The support-case reference to attach the bundle to.
    :param execution_ids: The incident executions whose output files and logs to
        send.
    """

    case_ref: NonEmptyStr
    execution_ids: list[UUID4] = Field(min_length=1)


class AtwSendLogResponse(BaseModel):
    """Represent one recorded diagnostics send attempt.

    Every field is always present on a stored attempt, so -- unlike returning the
    :class:`AtwSendLog` table model directly -- the generated client types them as
    required rather than optional.

    :param id: The attempt's UUID primary key.
    :param incident_id: The incident the attempt belongs to.
    :param case_ref: The support-case reference the attempt targeted.
    :param requested_by: Username of the support engineer who started it.
    :param status: The attempt's lifecycle status.
    :param started_at: When the worker picked it up, if it did.
    :param finished_at: When it reached a terminal status, if it did.
    :param created_at: When the attempt was requested.
    :param detail: The attempt's recorded evidence.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    incident_id: UUID4
    case_ref: NonEmptyStr
    requested_by: str
    status: AtwSendStatusEnum
    started_at: UTCDatetime | None
    finished_at: UTCDatetime | None
    created_at: UTCDatetime
    detail: dict[str, Any]


class AtwConfigResponse(BaseModel):
    """Report whether the incident send action is available.

    :param send_disabled_reasons: Why sending is unavailable; empty when the
        receiver is configured and the action is offered.
    """

    send_disabled_reasons: list[str]
