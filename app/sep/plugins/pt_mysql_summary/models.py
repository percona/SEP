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

"""Define the model-first create form and response model for the PtMysqlSummary plugin."""

from typing import Annotated

from app.core.utils.fields import NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    ArgFormat,
    HostRef,
    ServiceRef,
    Ui,
)
from app.sep.plugins.framework.responses import BaseTaskResponse


class PtMysqlSummaryForm(AppFormModel):
    """Single declaration of the PtMysqlSummary create form, request body, and schema source.

    Field declaration order is load-bearing: it fixes the CLI argument order
    (value args before flags) and the form section order (a section appears where
    its first field is declared). ``alert_on_fail`` is inherited from
    ``AppFormModel`` (rendered from the capability), so it is not declared here.
    """

    # --- Task section: identity, where it runs, what it targets --------------
    task_name: Annotated[NonEmptyStr, Ui(label="Task Name", section="task")]
    hostname: Annotated[
        NonEmptyStr, HostRef(), Ui(label="Executor Host", section="task")
    ]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,), check_connectivity=True),
        Ui(label="Database Host", section="task"),
    ]

    # --- Options section: the tool's own flags ------------------------------
    all_databases: Annotated[
        bool,
        ArgFormat(),  # derives the flag "--all-databases"
        Ui(
            label="All Databases",
            section="options",
            description="mysqldump and summarize every database",
        ),
    ] = False
    databases: Annotated[
        str,
        ArgFormat(),  # derives "--databases=${value}"; emitted only when non-empty
        Ui(
            label="Databases",
            section="options",
            default=None,
            description="Comma-separated database names to summarize",
        ),
    ] = ""
    sleep: Annotated[
        int,
        ArgFormat(),  # derives "--sleep=${value}"
        Ui(
            label="Sleep",
            section="options",
            description="Seconds to sleep while gathering status counters",
        ),
    ] = 10


class PtMysqlSummaryTaskResponse(BaseTaskResponse):
    """List/detail response for an PtMysqlSummary task.

    Subclass ``BaseTaskResponse`` and add plugin-specific fields here if needed;
    a plugin with no extras can pass ``BaseTaskResponse`` directly as
    ``response_model``.
    """
