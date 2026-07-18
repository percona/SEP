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

"""Define the model-first create form for the Golden Task app."""

from typing import Annotated

from app.core.utils.fields import NonEmptyStr
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.labels import EXECUTION_HOST_LABEL
from app.sep.apps.framework.form_dsl import (
    AppFormModel,
    ArgFormat,
    HostRef,
    ServiceRef,
    Ui,
)


class GoldenTaskForm(AppFormModel):
    """Declare the create/update body and ``GET /schema`` source for Golden Task.

    The single source of the JSON request body the server validates *and* the
    derived form. Replace these example fields with the task's real inputs:
    ``task_name`` is required by the framework, the ``ServiceRef`` resolves the
    target database service, the ``HostRef`` names the executor host the command
    runs on, and each ``ArgFormat`` field becomes a CLI argument.

    :param task_name: The unique name of the task.
    :param service_id: The Inventory id of the target database service.
    :param hostname: The executor host the command runs on.
    :param message: An example value argument passed to the command.
    """

    task_name: Annotated[NonEmptyStr, Ui(section="Task")]
    service_id: Annotated[
        int,
        ServiceRef(service_types=(ServiceTypeEnum.MYSQL,)),
        Ui(label="Database Host", section="Task"),
    ]
    hostname: Annotated[
        NonEmptyStr, HostRef(), Ui(label=EXECUTION_HOST_LABEL, section="Task")
    ]
    message: Annotated[
        str,
        ArgFormat(),
        Ui(section="Task", description="Example value argument"),
    ] = "hello"
