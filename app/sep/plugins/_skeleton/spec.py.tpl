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

"""Build the ``example-tool`` run-command spec from the validated Example form."""

import shlex

from app.sep.plugins.example.models import ExampleForm
from app.sep.plugins.framework.spec import (
    build_command_args,
    ResolvedEntities,
    RunCommandSpec,
)


def build_example_spec(
    form: ExampleForm, resolved: ResolvedEntities
) -> RunCommandSpec:
    """Assemble the ``example-tool`` run-command spec.

    Pure ``(form, resolved) -> RunCommandSpec``: the framework's
    ``assemble_envelope`` supplies the executor ``target``, ``_service_name``, and
    the connectivity meta around this spec. ``build_command_args`` emits the
    declarative value/flag args from the form's ``ArgFormat`` markers.

    :param form: The validated create form.
    :param resolved: The entities resolved from the form's reference fields; its
        ``service`` is the required ``ServiceRef`` selection.
    :return: The run-command spec consumed by ``assemble_envelope``.
    """
    service = resolved.service
    command = "example-tool"
    args = build_command_args(form)
    joined = shlex.join(args)
    return RunCommandSpec(
        command=command,
        args=joined,
        extra_meta={
            "_service_host": service.node.address,
            "_service_port": service.port,
            "_command_line": f"{command} {joined}",
        },
    )
