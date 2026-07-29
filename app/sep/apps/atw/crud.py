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

"""Define database operations for ATW incidents and their executions."""

from app.core.db.crud import BaseSQLModelChildManager, BaseSQLModelManager
from app.sep.apps.atw.models import AtwIncident, AtwIncidentExecution, AtwSendLog


class AtwIncidentManager(BaseSQLModelManager):
    """Manage AtwIncident CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for (``AtwIncident``).
    """

    Model = AtwIncident


class AtwIncidentExecutionManager(BaseSQLModelChildManager):
    """Manage AtwIncidentExecution CRUD operations, scoped to a parent incident.

    :cvar Model: The SQLModel class this manager handles (``AtwIncidentExecution``).
    :cvar ParentManager: The manager for the parent incident (``AtwIncidentManager``).
    :cvar connected_by: The foreign-key field linking an execution to its incident.
    """

    Model = AtwIncidentExecution
    ParentManager = AtwIncidentManager
    connected_by = "incident_id"


class AtwSendLogManager(BaseSQLModelChildManager):
    """Manage AtwSendLog CRUD operations, scoped to a parent incident.

    :cvar Model: The SQLModel class this manager handles (``AtwSendLog``).
    :cvar ParentManager: The manager for the parent incident (``AtwIncidentManager``).
    :cvar connected_by: The foreign-key field linking a send log to its incident.
    """

    Model = AtwSendLog
    ParentManager = AtwIncidentManager
    connected_by = "incident_id"
