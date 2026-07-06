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

"""Define the model-first create form and response model for the Example plugin."""

from typing import Annotated

from app.core.utils.fields import NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.plugins.framework.form_dsl import (
    AppFormModel,
    ArgFormat,
    Choices,
    HostRef,
    ServiceRef,
    Ui,
)
from app.sep.plugins.framework.responses import BaseTaskResponse


class ExampleForm(AppFormModel):
    """Single declaration of the Example create form, request body, and schema source.

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
    mode: Annotated[
        str,
        Choices(
            (
                ("check", "Check"),
                ("analyze", "Analyze"),
                ("optimize", "Optimize"),
            )
        ),
        ArgFormat("--${value}"),
        Ui(label="Mode", section="options", required=True),
    ] = "check"
    verbose: Annotated[
        bool,
        ArgFormat(),  # derives the "--verbose" flag
        Ui(
            label="Verbose",
            section="options",
            description="Print progress to STDERR",
        ),
    ] = False
    extra_args: Annotated[
        str,
        ArgFormat(),  # derives "--extra-args=${value}"; emitted only when non-empty
        Ui(
            label="Extra Args",
            section="options",
            default=None,
            description="Additional command-line arguments",
        ),
    ] = ""


class ExampleTaskResponse(BaseTaskResponse):
    """List/detail response for an Example task.

    Subclass ``BaseTaskResponse`` and add plugin-specific fields here if needed;
    a plugin with no extras can pass ``BaseTaskResponse`` directly as
    ``response_model``.
    """
