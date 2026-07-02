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

"""Models for the Dipper plugin."""

from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from app.core.utils.fields import NonEmptyStr
from app.sep.apps.dipper.constants import CollectorTypeEnum, DIPPER_PAYLOADS_DIR
from app.sep.apps.labels import EXECUTION_HOST_LABEL
from app.sep.snippets.models.snippet import BaseSnippet


class DipperScript(BaseSnippet):
    """Represent a Dipper payload script stored on the SEP server filesystem."""

    BASE_DIR: ClassVar[Path] = DIPPER_PAYLOADS_DIR


class DipperExecuteWrite(BaseModel):
    """Define the JSON body for ``POST /api/apps/dipper/``.

    :param service_id: Inventory ID of the database service to collect data from.
    :type service_id: int
    :param collector_type: Which collector script to run (environment or pmm).
    :type collector_type: CollectorTypeEnum
    :param executor_host: Nomad client hostname that will run the script.
    :type executor_host: NonEmptyStr
    :param sudo: Whether to invoke the script with ``sudo``. ``None`` defers
        to the script's own sudo policy (the default).
    :type sudo: bool | None
    :param args: Per-parameter arguments keyed by script parameter name. Validated
        server-side against the script's dynamic execution model.
    :type args: dict[str, Any]
    """

    service_id: int
    collector_type: CollectorTypeEnum = CollectorTypeEnum.ENVIRONMENT
    executor_host: NonEmptyStr = Field(title=EXECUTION_HOST_LABEL)
    sudo: bool | None = None
    args: dict[str, Any] = Field(default_factory=dict)


class DipperExecutionResponse(BaseModel):
    """Represent the response from ``POST /api/apps/dipper/``.

    :param task_id: ID of the task-history row created by the tasks API.
    :type task_id: int | None
    :param task_name: The execution task name used to dispatch the script.
    :type task_name: str
    :param snippet_filename: Composite path used to correlate history rows.
    :type snippet_filename: str
    :param service_id: Inventory ID of the database service.
    :type service_id: int
    :param collector_type: Collector type that was executed.
    :type collector_type: CollectorTypeEnum
    """

    task_id: int | None = None
    task_name: str
    snippet_filename: str
    service_id: int
    collector_type: CollectorTypeEnum
