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

"""Build the run-command spec for the Golden Task app."""

import shlex

from app.sep.apps.golden_task.models import GoldenTaskForm
from app.sep.apps.framework.spec import (
    build_command_args,
    ResolvedEntities,
    RunCommandSpec,
)


def build_golden_task_spec(
    form: GoldenTaskForm, resolved: ResolvedEntities
) -> RunCommandSpec:
    """Build the run-command spec from the validated form and resolved entities.

    The framework's ``assemble_envelope`` fills ``target`` (the ``HostRef``
    executor), ``_service_name``, and the connectivity keys around this spec; here
    we own the command, the ``shlex.join``'d declarative args derived from the
    form's ``ArgFormat`` markers, and the service host/port extras. Replace
    ``command`` with the executable the task runs.

    :param form: The validated create form.
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the ``ServiceRef`` selection (always present — the field is
        required).
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    return RunCommandSpec(
        command="echo",
        args=shlex.join(build_command_args(form)),
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
        },
    )
