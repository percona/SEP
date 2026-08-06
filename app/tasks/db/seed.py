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

"""Define the database initial data for the Tasks app."""

import logging
from copy import deepcopy

from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy_celery_beat.models import Period
from sqlmodel import col

from app.core.celery.models import IntervalSchedule
from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.core.utils.date_time import utc_now
from app.core.utils.fields import DatabaseDialect
from app.tasks.config import tasks_settings
from app.tasks.crud import TaskManager
from app.tasks.db import get_async_session_maker
from app.tasks.db.engine import engine
from app.tasks.models import (
    CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
    INVENTORY_SYNC_TASK_NAME,
    RUN_SCRIPT_OUTPUT_FILES_PATH,
    SYNC_RUNNING_TASKS_TASK_NAME,
    SYSTEM_USER,
    Task,
    TaskBackendEnum,
)

logger = logging.getLogger(__name__)

# POSIX sh preamble that aborts a Nomad allocation when
# ``now - scheduled_at`` exceeds the configured staleness threshold. Missing
# or empty meta values short-circuit to a no-op for rollback safety.
#
# NOTE: shell variables are referenced with the bareword form (``$name``) and
# never the brace form (``${name}``). Nomad interpolates ``${...}`` in
# ``raw_exec`` args through its own variable table before spawning the shell,
# and fails config validation for references it does not know (e.g. the shell
# local ``${elapsed}``). The ``""s`` after each variable name disambiguates the
# variable name from the trailing literal ``s`` so ``$elapseds`` is not parsed
# as a single (unset) variable name.
STALENESS_PREAMBLE_SHELL = (
    'if [ -n "$NOMAD_META_scheduled_at" ] && '
    '[ -n "$NOMAD_META_staleness_threshold_seconds" ]; then '
    "now=$(date +%s); "
    "elapsed=$((now - NOMAD_META_scheduled_at)); "
    'if [ "$elapsed" -gt "$NOMAD_META_staleness_threshold_seconds" ]; then '
    'echo "SEP_STALE_SKIP: elapsed=$elapsed""s '
    'threshold=$NOMAD_META_staleness_threshold_seconds""s"; '
    "exit 75; "
    "fi; "
    "fi"
)

_CHECK_STALENESS_TASK = {
    "Name": "check-staleness",
    "Lifecycle": {"hook": "prestart", "sidecar": False},
    "Driver": "raw_exec",
    "User": "",
    "Config": {
        "command": "sh",
        "args": ["-c", STALENESS_PREAMBLE_SHELL],
    },
    "Meta": {},
    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
}

_STALENESS_META_OPTIONAL = ["scheduled_at", "staleness_threshold_seconds"]

NOMAD_RUN_COMMAND = {
    "ID": "run-command",
    "Name": "run-command",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target", "command"],
        "MetaOptional": ["args", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "xargs",
                        "args": [
                            "--arg-file",
                            "args_file",
                            "${NOMAD_META_command}",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_args" }}',
                            "DestPath": "args_file",
                        },
                    ],
                },
            ],
        },
    ],
}

NOMAD_RUN_PYTHON = {
    "ID": "run-python",
    "Name": "run-python",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "required",
        "MetaRequired": ["target"],
        "MetaOptional": ["config", "config_nomad_variable", "requirements", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "prepare-env",
                    "Lifecycle": {"hook": "prestart", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            f"{STALENESS_PREAMBLE_SHELL}; "
                            "python3 -m venv --copies ${NOMAD_ALLOC_DIR}/venv;"
                            "${NOMAD_ALLOC_DIR}/venv/bin/pip install -r requirements.txt",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_requirements" }}',
                            "DestPath": "requirements.txt",
                        },
                    ],
                },
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            "gzip -d ${NOMAD_TASK_DIR}/script.py.gz;"
                            "${NOMAD_ALLOC_DIR}/venv/bin/python3"
                            " -u ${NOMAD_TASK_DIR}/script.py --config ${NOMAD_TASK_DIR}/script_config",
                        ],
                        "work_dir": "${NOMAD_TASK_DIR}/output_files",
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{- $var := env "NOMAD_META_config_nomad_variable" -}}{{- if $var -}}{{ with nomadVar $var }}{{ .config }}{{ end }}{{- else -}}{{ env "NOMAD_META_config" }}{{- end -}}',
                            "DestPath": "local/script_config",
                        },
                        {
                            "EmbeddedTmpl": ".keep",
                            "DestPath": "local/output_files/.keep",
                        },
                    ],
                    "DispatchPayload": {"file": "script.py.gz"},
                },
                {
                    "Name": "clean-up",
                    "Lifecycle": {"hook": "poststop", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "rm",
                        "args": [
                            "-rf",
                            "${NOMAD_ALLOC_DIR}/venv",
                            "requirements.txt",
                            "script_config",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                },
            ],
        },
    ],
}

NOMAD_EXEC_ARTIFACT = {
    "ID": "exec-artifact",
    "Name": "exec-artifact",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": [
            "target",
            "snippet_source",
            "interpreter",
            "md5_checksum",
        ],
        "MetaOptional": ["args", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "xargs",
                        "args": [
                            "--arg-file",
                            "${NOMAD_TASK_DIR}/args_file",
                            "env",
                            "-S",
                            "${NOMAD_META_interpreter}",
                            "${NOMAD_TASK_DIR}/script",
                        ],
                        "work_dir": "${NOMAD_TASK_DIR}/output_files",
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_args" }}',
                            "DestPath": "local/args_file",
                        },
                        {
                            "EmbeddedTmpl": ".keep",
                            "DestPath": "local/output_files/.keep",
                        },
                    ],
                    "Artifacts": [
                        {
                            "GetterSource": "${NOMAD_META_snippet_source}",
                            "GetterMode": "file",
                            "RelativeDest": "local/script",
                            "GetterOptions": {
                                "checksum": "md5:${NOMAD_META_md5_checksum}",
                            },
                            "GetterInsecure": True,
                        }
                    ],
                },
            ],
        },
    ],
}

NOMAD_EXEC_PYTHON_ARTIFACT = {
    "ID": "exec-python-artifact",
    "Name": "exec-python-artifact",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": [
            "target",
            "snippet_source",
            "interpreter",
            "md5_checksum",
        ],
        "MetaOptional": ["args", "requirements", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "PreventRescheduleOnLost": True,
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "prepare-env",
                    "Lifecycle": {"hook": "prestart", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            f"{STALENESS_PREAMBLE_SHELL}; "
                            "python3 -m venv --copies ${NOMAD_ALLOC_DIR}/venv;"
                            "${NOMAD_ALLOC_DIR}/venv/bin/pip install -r requirements.txt",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_requirements" }}',
                            "DestPath": "requirements.txt",
                        },
                    ],
                },
                {
                    "Name": "run-script",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            "PYTHON_CMD=${NOMAD_ALLOC_DIR}/venv/bin/python3;"
                            'case "${NOMAD_META_interpreter}" in "sudo "*) '
                            'PYTHON_CMD="sudo ${NOMAD_ALLOC_DIR}/venv/bin/python3";; esac;'
                            "xargs --arg-file ${NOMAD_TASK_DIR}/args_file -- "
                            "$PYTHON_CMD -u ${NOMAD_TASK_DIR}/script",
                        ],
                        "work_dir": "${NOMAD_TASK_DIR}/output_files",
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": '{{ env "NOMAD_META_args" }}',
                            "DestPath": "local/args_file",
                        },
                        {
                            "EmbeddedTmpl": ".keep",
                            "DestPath": "local/output_files/.keep",
                        },
                    ],
                    "Artifacts": [
                        {
                            "GetterSource": "${NOMAD_META_snippet_source}",
                            "GetterMode": "file",
                            "RelativeDest": "local/script",
                            "GetterOptions": {
                                "checksum": "md5:${NOMAD_META_md5_checksum}",
                            },
                            "GetterInsecure": True,
                        }
                    ],
                },
                {
                    "Name": "clean-up",
                    "Lifecycle": {"hook": "poststop", "sidecar": False},
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "rm",
                        "args": [
                            "-rf",
                            "${NOMAD_ALLOC_DIR}/venv",
                            "requirements.txt",
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                },
            ],
        },
    ],
}

# Nomad's Consul Template engine processes EmbeddedTmpl with {{ }} as directives.
# Ansible playbooks also use {{ }} for Jinja2 expressions. Use these sentinels to
# embed literal Jinja2 braces that survive Nomad rendering unchanged.
_NTL_OPEN = '{{ "{{" }}'   # rendered by Nomad → {{
_NTL_CLOSE = '{{ "}}" }}'  # rendered by Nomad → }}

# Ansible playbook for upgrading OS packages on an executor host.
# Embedded directly in the Nomad job spec via EmbeddedTmpl so no out-of-band
# playbook deployment to executor nodes is required.
#
# Runs on both Debian- and RHEL-family hosts. Facts are gathered (subset ``min``)
# because the branch below keys on ``ansible_facts['os_family']`` -- a full-system
# upgrade is the one operation with no portable module spelling: apt exposes it as
# the ``upgrade`` parameter, dnf as ``name: "*"``. Named-package upgrades use
# ansible.builtin.package and need no branch.
#
# Meta inputs (all optional):
#   packages        — space-separated list of package names; omit for a full upgrade
#   restart_service — systemd unit to restart after upgrade (e.g. "mysql" or "mongod")
_OS_UPGRADE_PLAYBOOK_TMPL = (
    "---\n"
    "- name: Upgrade executor host packages\n"
    "  hosts: localhost\n"
    "  connection: local\n"
    "  become: true\n"
    "  gather_facts: true\n"
    "  gather_subset:\n"
    "    - min\n"
    "  vars:\n"
    '    packages: ""\n'
    '    restart_service: ""\n'
    "  tasks:\n"
    "    - name: Full upgrade (Debian family)\n"
    "      ansible.builtin.apt:\n"
    "        update_cache: true\n"
    "        cache_valid_time: 0\n"
    "        upgrade: dist\n"
    "        autoremove: true\n"
    "        autoclean: true\n"
    "      when: not packages and ansible_facts['os_family'] == 'Debian'\n"
    "\n"
    "    - name: Full upgrade (RHEL family)\n"
    "      ansible.builtin.dnf:\n"
    '        name: "*"\n'
    "        state: latest\n"
    "        update_cache: true\n"
    "      when: not packages and ansible_facts['os_family'] == 'RedHat'\n"
    "\n"
    # ansible.builtin.package is a thin name/state wrapper with no cache control,
    # so a named upgrade refreshes the cache through the concrete module first --
    # otherwise apt resolves "latest" against a stale index.
    "    - name: Refresh apt cache before a named upgrade\n"
    "      ansible.builtin.apt:\n"
    "        update_cache: true\n"
    "        cache_valid_time: 0\n"
    "      when: packages and ansible_facts['os_family'] == 'Debian'\n"
    "\n"
    "    - name: Refresh dnf cache before a named upgrade\n"
    "      ansible.builtin.dnf:\n"
    "        update_cache: true\n"
    "      when: packages and ansible_facts['os_family'] == 'RedHat'\n"
    "\n"
    "    - name: Upgrade specific packages\n"
    "      ansible.builtin.package:\n"
    # packages.split() converts the space-separated meta value into a list.
    # Nomad expands ${NOMAD_META_packages} before sh runs; single-quoting in
    # the command preserves spaces so the whole value reaches Ansible as one arg.
    f'        name: "{_NTL_OPEN} packages.split() {_NTL_CLOSE}"\n'
    "        state: latest\n"
    "      when: packages\n"
    "\n"
    "    - name: Restart service after upgrade\n"
    "      ansible.builtin.systemd:\n"
    f'        name: "{_NTL_OPEN} restart_service {_NTL_CLOSE}"\n'
    "        state: restarted\n"
    "        daemon_reload: true\n"
    "      when: restart_service\n"
)

NOMAD_OS_UPGRADE = {
    "ID": "os-upgrade",
    "Name": "os-upgrade",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target"],
        "MetaOptional": ["packages", "restart_service", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "run-playbook",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            # ${NOMAD_META_packages} and ${NOMAD_META_restart_service} are
                            # expanded by Nomad before sh runs. Single-quoting each value
                            # preserves spaces (e.g. "pkg-a pkg-b") as one -e argument.
                            # Empty optional meta expands to "" which Ansible treats as falsy.
                            (
                                "ANSIBLE_CONNECTION=local"
                                " ANSIBLE_CONFIG=${NOMAD_TASK_DIR}/ansible.cfg"
                                " ansible-playbook"
                                " -c local"
                                " -i localhost,"
                                " -e packages='${NOMAD_META_packages}'"
                                " -e restart_service='${NOMAD_META_restart_service}'"
                                " ${NOMAD_TASK_DIR}/os_upgrade.yml"
                            ),
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": (
                                "[defaults]\n"
                                "connection = local\n"
                                "gathering = explicit\n"
                                "stdout_callback = yaml\n"
                            ),
                            "DestPath": "local/ansible.cfg",
                        },
                        {
                            "EmbeddedTmpl": _OS_UPGRADE_PLAYBOOK_TMPL,
                            "DestPath": "local/os_upgrade.yml",
                        },
                    ],
                },
            ],
        },
    ],
}

_DISCOVER_MONGO_PARSER_PY = (
    "import json, sys\n"
    "try:\n"
    "    d = json.load(sys.stdin)\n"
    "except Exception as e:\n"
    "    print(json.dumps({'role': 'unreachable', 'error': str(e)}))\n"
    "    sys.exit(0)\n"
    "if d.get('arbiterOnly'):\n"
    "    role = 'arbiter'\n"
    "elif d.get('isWritablePrimary'):\n"
    "    role = 'primary'\n"
    "elif d.get('secondary'):\n"
    "    role = 'secondary'\n"
    "elif 'setName' in d:\n"
    "    role = 'secondary'\n"
    "else:\n"
    "    role = 'standalone'\n"
    "out = {'role': role}\n"
    "if 'setName' in d:\n"
    "    out['setName'] = d['setName']\n"
    "if 'me' in d:\n"
    "    out['me'] = d['me']\n"
    "if 'hosts' in d:\n"
    "    out['hosts'] = d['hosts']\n"
    "if 'mongodVersion' in d:\n"
    "    out['mongodVersion'] = d['mongodVersion']\n"
    "print(json.dumps(out))\n"
)

NOMAD_DISCOVER_MONGO = {
    "ID": "discover-mongo",
    "Name": "discover-mongo",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target"],
        "MetaOptional": [*_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "discover",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            # Credentials from mongo_terraform_ansible group_vars/all.yml.
                            # On failure emit unreachable JSON and exit 0 so SEP records
                            # SUCCESS with the error payload rather than FAILED.
                            # Bareword $VAR avoids Nomad ${} interpolation on shell-local vars.
                            # Merge db.version() into db.hello() so the parser gets
                            # both role info and the running mongod version in one call.
                            (
                                "OUTPUT=$(mongosh admin"
                                " -u root -p percona"
                                " --port 27017 --host 127.0.0.1"
                                " --quiet --eval"
                                " 'JSON.stringify(Object.assign(db.hello(),{mongodVersion:db.version()}))'"
                                " 2>/dev/null);"
                                ' if [ $? -ne 0 ] || [ -z "$OUTPUT" ]; then'
                                " printf '{\"role\":\"unreachable\",\"error\":\"mongosh failed\"}\\n';"
                                " exit 0;"
                                " fi;"
                                ' echo "$OUTPUT" | python3 ${NOMAD_TASK_DIR}/parse_role.py'
                            ),
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": _DISCOVER_MONGO_PARSER_PY,
                            "DestPath": "local/parse_role.py",
                        },
                    ],
                },
            ],
        },
    ],
}

# MongoDB rolling upgrade playbook — mirrors mongo_terraform_ansible/ansible/mongod_install.yml.
# Meta inputs:
#   mongo_release   — Percona release channel, e.g. "psmdb-80" (required)
#   mongo_version   — exact package version prefix, e.g. "8.0.12-7" (optional; omit for latest)
#   restart_service — systemd unit to restart (default: mongod)
#
# Runs on both Debian- and RHEL-family hosts. percona-release itself is portable,
# and the PSMDB package names are identical on both, so only two things branch:
# the cache refresh, and the pinned-version spelling -- apt separates name and
# version with "=" (pkg=8.0.12-7*), dnf with "-" (pkg-8.0.12-7*).
_UPGRADE_MONGO_PLAYBOOK_TMPL = (
    "---\n"
    "- name: Upgrade MongoDB on executor host\n"
    "  hosts: localhost\n"
    "  connection: local\n"
    "  become: true\n"
    "  gather_facts: true\n"
    "  gather_subset:\n"
    "    - min\n"
    "  vars:\n"
    '    mongo_release: "psmdb-80"\n'
    '    mongo_version: ""\n'
    '    restart_service: "mongod"\n'
    "  tasks:\n"
    "    - name: Enable Percona release channel\n"
    "      ansible.builtin.command:\n"
    f"        cmd: percona-release enable {_NTL_OPEN} mongo_release {_NTL_CLOSE}\n"
    "\n"
    "    - name: Refresh apt cache (Debian family)\n"
    "      ansible.builtin.apt:\n"
    "        update_cache: true\n"
    "        cache_valid_time: 0\n"
    "      when: ansible_facts['os_family'] == 'Debian'\n"
    "\n"
    "    - name: Refresh dnf cache (RHEL family)\n"
    "      ansible.builtin.dnf:\n"
    "        update_cache: true\n"
    "      when: ansible_facts['os_family'] == 'RedHat'\n"
    "\n"
    "    - name: Install MongoDB packages (latest in channel)\n"
    "      ansible.builtin.package:\n"
    "        name:\n"
    "          - percona-server-mongodb\n"
    "          - percona-mongodb-mongosh\n"
    "        state: latest\n"
    "      when: not mongo_version\n"
    "\n"
    "    - name: Install MongoDB packages (pinned version, Debian family)\n"
    "      ansible.builtin.apt:\n"
    "        name:\n"
    f"          - percona-server-mongodb={_NTL_OPEN} mongo_version {_NTL_CLOSE}*\n"
    "          - percona-mongodb-mongosh\n"
    "        state: present\n"
    "        allow_downgrade: true\n"
    "        update_cache: false\n"
    "      when: mongo_version and ansible_facts['os_family'] == 'Debian'\n"
    "\n"
    "    - name: Install MongoDB packages (pinned version, RHEL family)\n"
    "      ansible.builtin.dnf:\n"
    "        name:\n"
    f"          - percona-server-mongodb-{_NTL_OPEN} mongo_version {_NTL_CLOSE}*\n"
    "          - percona-mongodb-mongosh\n"
    "        state: present\n"
    "        allow_downgrade: true\n"
    "        update_cache: false\n"
    "      when: mongo_version and ansible_facts['os_family'] == 'RedHat'\n"
    "\n"
    "    - name: Restart MongoDB service\n"
    "      ansible.builtin.systemd:\n"
    f'        name: "{_NTL_OPEN} restart_service {_NTL_CLOSE}"\n'
    "        state: restarted\n"
    "        daemon_reload: true\n"
    "\n"
    "    - name: Wait for MongoDB to accept connections\n"
    "      ansible.builtin.command:\n"
    "        cmd: mongosh admin -u root -p percona --port 27017 --host 127.0.0.1 --quiet --eval 'db.hello()'\n"
    "      register: _mongo_ready\n"
    "      retries: 60\n"
    "      delay: 1\n"
    "      until: _mongo_ready.rc == 0\n"
    "      changed_when: false\n"
)

NOMAD_UPGRADE_MONGO = {
    "ID": "upgrade-mongo",
    "Name": "upgrade-mongo",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target", "mongo_release"],
        "MetaOptional": ["mongo_version", "restart_service", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "run-playbook",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            (
                                "ANSIBLE_CONNECTION=local"
                                " ANSIBLE_CONFIG=${NOMAD_TASK_DIR}/ansible.cfg"
                                " ansible-playbook"
                                " -c local"
                                " -i localhost,"
                                " -e mongo_release='${NOMAD_META_mongo_release}'"
                                " -e mongo_version='${NOMAD_META_mongo_version}'"
                                " -e restart_service='${NOMAD_META_restart_service}'"
                                " ${NOMAD_TASK_DIR}/upgrade_mongo.yml"
                            ),
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": (
                                "[defaults]\n"
                                "connection = local\n"
                                "gathering = explicit\n"
                                "stdout_callback = yaml\n"
                            ),
                            "DestPath": "local/ansible.cfg",
                        },
                        {
                            "EmbeddedTmpl": _UPGRADE_MONGO_PLAYBOOK_TMPL,
                            "DestPath": "local/upgrade_mongo.yml",
                        },
                    ],
                },
            ],
        },
    ],
}

NOMAD_RUN_ANSIBLE = {
    "ID": "run-ansible",
    "Name": "run-ansible",
    "Type": "batch",
    "Datacenters": ["*"],
    "Constraints": [
        {
            "LTarget": "${node.unique.name}",
            "RTarget": "${NOMAD_META_target}",
            "Operand": "=",
        },
    ],
    "ParameterizedJob": {
        "Payload": "forbidden",
        "MetaRequired": ["target", "playbook"],
        "MetaOptional": ["extra_vars", *_STALENESS_META_OPTIONAL],
    },
    "TaskGroups": [
        {
            "Name": "execution",
            "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
            "ReschedulePolicy": {"Attempts": 0},
            "Tasks": [
                deepcopy(_CHECK_STALENESS_TASK),
                {
                    "Name": "run-playbook",
                    "Driver": "raw_exec",
                    "User": "",
                    "Config": {
                        "command": "sh",
                        "args": [
                            "-c",
                            # Three independent local-mode guards:
                            # 1. ANSIBLE_CONNECTION=local  — env var, set before Ansible reads config
                            # 2. ANSIBLE_CONFIG points to the template-written ansible.cfg below
                            # 3. -c local CLI flag          — overrides any playbook-level connection:
                            #
                            # ${NOMAD_META_*} tokens are expanded by Nomad before sh runs.
                            # Shell-local vars use bareword form to avoid Nomad interpolation errors.
                            # Single-quoting ${NOMAD_META_extra_vars} after Nomad expands it ensures
                            # the whole value is passed as one -e argument; empty string is a no-op.
                            (
                                "ANSIBLE_CONNECTION=local"
                                " ANSIBLE_CONFIG=${NOMAD_TASK_DIR}/ansible.cfg"
                                " ansible-playbook"
                                " -c local"
                                " -i localhost,"
                                " -e '${NOMAD_META_extra_vars}'"
                                " ${NOMAD_META_playbook}"
                            ),
                        ],
                    },
                    "Meta": {},
                    "RestartPolicy": {"Attempts": 0, "Mode": "fail"},
                    "Templates": [
                        {
                            "EmbeddedTmpl": (
                                "[defaults]\n"
                                "connection = local\n"
                                "gathering = explicit\n"
                                "stdout_callback = yaml\n"
                            ),
                            "DestPath": "local/ansible.cfg",
                        },
                    ],
                },
            ],
        },
    ],
}

SYSTEM_TASKS = [
    Task(
        name="run-command",
        data=NOMAD_RUN_COMMAND,
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="run-python",
        data=NOMAD_RUN_PYTHON,
        protected=True,
        anonymize_mask=None,
        output_files_path=RUN_SCRIPT_OUTPUT_FILES_PATH,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="exec-artifact",
        data=NOMAD_EXEC_ARTIFACT,
        protected=True,
        anonymize_mask=None,
        output_files_path=RUN_SCRIPT_OUTPUT_FILES_PATH,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="exec-python-artifact",
        data=NOMAD_EXEC_PYTHON_ARTIFACT,
        protected=True,
        anonymize_mask=None,
        output_files_path=RUN_SCRIPT_OUTPUT_FILES_PATH,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="discover-mongo",
        data=NOMAD_DISCOVER_MONGO,
        owner="ANSIBLE",
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="upgrade-mongo",
        data=NOMAD_UPGRADE_MONGO,
        owner="ANSIBLE",
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="os-upgrade",
        data=NOMAD_OS_UPGRADE,
        owner="ANSIBLE",
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name="run-ansible",
        data=NOMAD_RUN_ANSIBLE,
        owner="ANSIBLE",
        protected=True,
        anonymize_mask=None,
        created_by=SYSTEM_USER,
    ),
    Task(
        name=INVENTORY_SYNC_TASK_NAME,
        data={
            "callable": "app.sep.apps.inventory.sync.run_scheduled_inventory_sync",
            "target": "local",
        },
        backend=TaskBackendEnum.CELERY,
        protected=True,
        created_by=SYSTEM_USER,
    ),
]

# Import plugin tasks
try:
    from app.sep.plugins.mum.task import get_mum_tasks

    SYSTEM_TASKS.extend(
        Task(
            name=mum_task.name,
            data=mum_task.data,
            backend=mum_task.backend,
            owner=mum_task.owner,
            protected=mum_task.protected,
            alert_on_fail=mum_task.alert_on_fail,
            anonymize_mask=None,
            created_by=SYSTEM_USER,
        )
        for mum_task in get_mum_tasks()
    )
except ImportError:
    # MUM plugin not available, skip
    pass

SYSTEM_PERIODIC_TASKS = [
    SystemPeriodicTaskSchedule(
        schedule=IntervalSchedule(every=30, period=Period.SECONDS),
        tasks=[
            SystemPeriodicTaskData(
                name=SYNC_RUNNING_TASKS_TASK_NAME,
                task_name="app.tasks.celery.sync_running_tasks",
                extra_kwargs={"expire_seconds": 30},
            ),
        ],
    )
]

_nomad_cert_schedule = tasks_settings.NOMAD.check_cert_expiry_interval
if _nomad_cert_schedule is not None:
    SYSTEM_PERIODIC_TASKS.append(
        SystemPeriodicTaskSchedule(
            schedule=_nomad_cert_schedule,
            tasks=[
                SystemPeriodicTaskData(
                    name=CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
                    task_name="app.tasks.celery.check_nomad_cert_expiry",
                ),
            ],
        ),
    )

_log_purge_schedule = tasks_settings.LOG_PURGE_INTERVAL
if _log_purge_schedule is not None:
    SYSTEM_PERIODIC_TASKS.append(
        SystemPeriodicTaskSchedule(
            schedule=_log_purge_schedule,
            tasks=[
                SystemPeriodicTaskData(
                    name="tasks__purge_task_history_logs",
                    task_name="app.tasks.celery.purge_task_history_logs",
                ),
            ],
        ),
    )


async def init_tasks_db() -> None:
    """Initialize the Tasks database with system tasks and periodic tasks."""
    async_session = get_async_session_maker()
    async with async_session() as session:
        system_tasks_names = []
        for task in SYSTEM_TASKS:
            system_tasks_names.append(task.name)
            created_task, created = await TaskManager.get_or_create(
                session, task, {"name"}
            )
            if created:
                logger.info("Created system task %s", created_task.name)
            elif created_task.data != task.data:
                await TaskManager.update(
                    session,
                    created_task,
                    task,
                    flag_modified_fields=["data"],
                    last_updated_by=SYSTEM_USER,
                )
                logger.info(
                    "Updated system task %s with new data: %s",
                    created_task.name,
                    task.data,
                )
            elif created_task.model_dump(
                exclude={"id", "created_at", "updated_at", "deleted_at"}
            ) != task.model_dump(
                exclude={"id", "created_at", "updated_at", "deleted_at"}
            ):
                logger.debug("Created task: %s", created_task.model_dump())
                logger.debug("New task: %s", task.model_dump())
                await TaskManager.update(session, created_task, task)
                logger.info("Updated system task %s", created_task.name)
        await TaskManager.update_where(
            session,
            {"deleted_at": None},
            col(Task.name).in_(system_tasks_names),
            col(Task.deleted_at).is_not(None),
        )
        delete_result = await TaskManager.delete_unattached_system_tasks(
            session, exclude_task_names=system_tasks_names
        )
        if delete_result.rowcount:
            logger.info(
                "Deleted %s system tasks that are no longer needed.",
                delete_result.rowcount,
            )
        update_delete_result = await TaskManager.update_where(
            session,
            {"deleted_at": utc_now()},
            col(Task.name).not_in(system_tasks_names),
            col(Task.protected).is_(True),
            col(Task.deleted_at).is_(None),
        )
        if update_delete_result.rowcount:
            logger.info(
                "Marked %s unused system tasks with attached runs as deleted.",
                update_delete_result.rowcount,
            )
    await init_periodic_tasks_db(SYSTEM_PERIODIC_TASKS, "tasks__")


async def verify_taskhistory_execution_request_is_jsonb() -> None:
    """Fail fast if ``taskhistory.execution_request`` is not ``jsonb`` on PostgreSQL.

    Defend against a deploy that ships the ``@>`` dispatch dedup code
    without running the corresponding Alembic migration. ``compare_type``
    intentionally suppresses the ``json``/``jsonb`` diff during autogeneration,
    so ``make checkmigrations`` cannot detect this skew. Without this guard,
    the first dispatch hits ``operator does not exist: json @> jsonb`` at
    runtime; with it, the Tasks app refuses to start until the column is
    converted. The check is a no-op on SQLite and MySQL, where the corresponding
    migration is also a no-op.

    Use SQLAlchemy's reflection inspector rather than a raw
    ``information_schema`` query so the dialect-specific type mapping is what
    decides whether the column is ``JSONB`` or plain ``JSON``.

    :raises RuntimeError: If the PostgreSQL column type is not ``jsonb``.
    """
    if not engine.dialect.name.startswith(DatabaseDialect.POSTGRESQL):
        return
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_columns("taskhistory")
        )
    for column in columns:
        if column["name"] != "execution_request":
            continue
        if isinstance(column["type"], JSONB):
            return
        raise RuntimeError(
            f"taskhistory.execution_request is {type(column['type']).__name__!r}, "
            "expected 'JSONB'. Run the Tasks API Alembic migrations (SEP-988) "
            "before starting the app."
        )
    raise RuntimeError(
        "taskhistory.execution_request column not found. Run the Tasks API "
        "Alembic migrations (SEP-988) before starting the app."
    )
