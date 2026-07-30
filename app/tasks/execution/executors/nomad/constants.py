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

"""Define Nomad-owned constants for allocation layout and Nomad-only system tasks.

Imports nothing from the rest of the tasks or sep packages so seed and framework
specs can use these values without the Nomad executor import graph.
"""

#: Allocation-relative output-files directory of every job spec that pins its
#: ``run-script`` task's ``work_dir`` to ``${NOMAD_TASK_DIR}/output_files``
#: (``run-python``, ``exec-artifact``, ``exec-python-artifact``). It is the
#: :attr:`~app.tasks.models.TaskBase.output_files_path` those specs run under,
#: so a payload's working directory and the path SEP reads its files back from
#: are the same place. ``run-command`` pins no ``work_dir`` and so has no
#: output-files path. The ``run-script/local/`` prefix is the Nomad allocation
#: layout (``run-script`` task name + ``${NOMAD_TASK_DIR}``).
RUN_SCRIPT_OUTPUT_FILES_PATH = "run-script/local/output_files"

#: Seeded name of the Nomad-only periodic task that checks TLS cert expiry.
CHECK_NOMAD_CERT_EXPIRY_TASK_NAME = "tasks__check_nomad_cert_expiry"
