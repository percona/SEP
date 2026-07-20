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

from pydantic import BaseModel, ConfigDict, Field, UUID4
from sqlalchemy import UniqueConstraint
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db.models import BaseUUIDSQLModel
from app.core.utils.date_time import utc_now
from app.core.utils.fields import NonEmptyStr, UTCDatetime


def _default_incident_name() -> str:
    """Build the default incident name embedding the creation time.

    :return: A timestamped name of the form ``Incident YYYY-MM-DD HH:MM``.
    """
    return f"Incident {utc_now():%Y-%m-%d %H:%M}"


class AtwIncidentBase(SQLModel):
    """Define the incident fields shared by the create payload and the DB table.

    :param name: Human-readable incident label; defaults to a timestamped name.
    :param servicenow_case: Optional ServiceNow support-case reference.
    """

    name: NonEmptyStr = SQLField(default_factory=_default_incident_name)
    servicenow_case: str | None = SQLField(default=None)


class AtwIncident(BaseUUIDSQLModel, AtwIncidentBase, table=True):
    """Represent a named grouping of diagnostic snippet executions per support case.

    :param created_by: Username of the support engineer who created the incident.
    :param executions: The snippet executions grouped under this incident.
    """

    __tablename__ = "atw_incident"

    created_by: str = SQLField(nullable=False)
    executions: list["AtwIncidentExecution"] = Relationship(
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
    :param servicenow_case: New ServiceNow case reference; an explicit null clears it.
    """

    name: NonEmptyStr = Field(default=None)
    servicenow_case: str | None = None


class AtwIncidentResponse(BaseModel):
    """Represent a persisted diagnostic incident.

    Every field is always present on a stored incident, so — unlike returning
    the :class:`AtwIncident` table model directly — the generated client types
    them as required rather than optional.

    :param id: The incident's UUID primary key.
    :param name: Human-readable incident label.
    :param servicenow_case: ServiceNow support-case reference, if set.
    :param created_by: Username of the support engineer who created the incident.
    :param created_at: When the incident was created.
    :param updated_at: When the incident was last updated, if ever.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID4
    name: NonEmptyStr
    servicenow_case: str | None
    created_by: str
    created_at: UTCDatetime
    updated_at: UTCDatetime | None


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
