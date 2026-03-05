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

"""Define base exceptions for task execution."""


class TaskDataNotFoundInExecutorError(Exception):
    """Define exception for when task data is not found in executor.

    Subclasses can pass optional structured context for HTTP response details:

    :param message: Human-readable description of the failure.
    :param executor_name: Name of the executor where the resource was missing
        (e.g. `"nomad"`).
    :param resource_type: Type of missing resource (e.g. `"job"`,
        `"allocation"`).
    :param resource_id: Identifier for the missing resource when available
        (job ID, allocation ID, filter expression, etc.).
    """

    def __init__(
        self,
        message: str = "",
        /,
        *,
        executor_name: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.executor_name = executor_name
        self.resource_type = resource_type
        self.resource_id = resource_id
