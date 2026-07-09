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

"""Build the ``run-python`` pgBackRest spec for the PostgreSQL Backups app.

:func:`build_backup_pg_spec` is the pure ``(form, resolved) -> RunPythonSpec``
builder fed to the framework's three-phase create path (and reused by the legacy
Jinja form path via ``deps.build_backup_task_payload``), so a backup task's Nomad
payload is byte-identical regardless of the call origin. It reuses the kept
``BackupConfig`` / ``BackupConfigAll`` / ``BackupConfigServer`` validators to
serialise the pgBackRest YAML config and injects :attr:`BackupType.PGBACKREST`
(not a form field). The framework's ``assemble_envelope`` supplies the executor
``target``, ``_service_name``, and the connectivity meta keys around this spec.
"""

import yaml
from fastapi.encoders import jsonable_encoder

from app.core.utils.path import payload_uri
from app.sep.apps.backup_pg.models import (
    BackupConfig,
    BackupConfigAll,
    BackupConfigServer,
    BackupPgForm,
    BackupType,
)
from app.sep.apps.framework.spec import ResolvedEntities, RunPythonSpec

_REQUIREMENTS = "packaging\nPyYAML"


def build_backup_pg_spec(
    form: BackupPgForm, _resolved: ResolvedEntities
) -> RunPythonSpec:
    """Build the ``run-python`` pgBackRest spec from the validated form.

    Serialize the pgBackRest ``config`` YAML from the kept ``BackupConfig``
    validators — the ``ALL_SERVERS`` general settings from the form's
    pgbackrest_* / logging / backup-dir fields and a single ``SERVER_LIST`` entry
    aliased by the stanza, pinned to ``localhost``, with the backup type fixed to
    :attr:`BackupType.PGBACKREST`. The framework's ``assemble_envelope`` fills
    ``target`` (the executor ``HostRef``), ``_service_name``, and the connectivity
    keys — including the resolved service port — around this spec.

    :param form: The validated create form (a ``BackupPgForm``).
    :param _resolved: The entities resolved from the form's reference fields, part
        of the framework's ``(form, resolved) -> RunPythonSpec`` builder contract.
        Unused here: the ``SERVER_LIST`` host is the fixed ``localhost`` and the
        service port is carried by ``assemble_envelope``'s connectivity meta, not
        the dumped config.
    :return: The run-python spec consumed by ``assemble_envelope``.
    """
    all_config = form.model_dump(
        exclude={"task_name", "hostname", "service_id", "stanza"}
    )

    server_config = {
        "alias": form.stanza,
        "backup_type": BackupType.PGBACKREST,
        "host": "localhost",
    }

    backup_config = BackupConfig(
        all_servers=BackupConfigAll.model_validate(all_config),
        server_list=[BackupConfigServer.model_validate(server_config)],
    )

    return RunPythonSpec(
        config=yaml.dump(
            jsonable_encoder(backup_config, by_alias=True, exclude_none=True)
        ),
        requirements=_REQUIREMENTS,
        payload=payload_uri(__file__, "payload"),
    )
