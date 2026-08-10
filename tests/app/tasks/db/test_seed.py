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

"""Define tests for the Tasks database seed module."""

import subprocess
import time

import pytest

from app.sep.apps.inventory.models import INVENTORY_SYNC_TASK_NAME
from app.tasks.config import tasks_settings
from app.tasks.db.seed import (
    _CHECK_STALENESS_TASK,
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
    NOMAD_RUN_COMMAND,
    NOMAD_RUN_PYTHON,
    STALENESS_PREAMBLE_SHELL,
    SYSTEM_PERIODIC_TASKS,
    SYSTEM_TASKS,
)
from app.tasks.execution.executors.nomad.steps import NomadStep
from app.tasks.models import (
    CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
    INTERNAL_TASK_NAMES,
    SYNC_RUNNING_TASKS_TASK_NAME,
    TaskBackendEnum,
)

NOMAD_TEMPLATES_WITH_STALENESS = [
    NOMAD_RUN_COMMAND,
    NOMAD_RUN_PYTHON,
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
]
PYTHON_TEMPLATES_WITH_PREPARE_ENV = [NOMAD_RUN_PYTHON, NOMAD_EXEC_PYTHON_ARTIFACT]
STALE_EXIT_CODE = 75
STALE_ELAPSED_SECONDS = 7200
FRESH_ELAPSED_SECONDS = 1


class TestNomadStepNameParity:
    """Assert every Nomad task Name in seed templates is a NomadStep member."""

    def test_every_seed_task_name_is_nomad_step_member(self) -> None:
        """Walk all four NOMAD_* templates + _CHECK_STALENESS_TASK Names."""
        names: list[object] = [_CHECK_STALENESS_TASK["Name"]]
        for template in NOMAD_TEMPLATES_WITH_STALENESS:
            names.extend(task["Name"] for task in template["TaskGroups"][0]["Tasks"])

        for name in names:
            assert isinstance(name, NomadStep), f"{name!r} is not a NomadStep"
            assert name in NomadStep


class TestSystemTasks:
    """Test SYSTEM_TASKS seed data."""

    def test_inventory_sync_task_exists(self) -> None:
        """Assert inventory-sync task is defined in SYSTEM_TASKS."""
        task_names = [t.name for t in SYSTEM_TASKS]
        assert "inventory-sync" in task_names

    def test_inventory_sync_task_has_celery_backend(self) -> None:
        """Assert inventory-sync task uses the CELERY backend."""
        task = next(t for t in SYSTEM_TASKS if t.name == "inventory-sync")
        assert task.backend == TaskBackendEnum.CELERY

    def test_inventory_sync_task_has_callable(self) -> None:
        """Assert inventory-sync task data contains a callable path."""
        task = next(t for t in SYSTEM_TASKS if t.name == "inventory-sync")
        assert "callable" in task.data
        assert task.data["callable"].endswith("run_scheduled_inventory_sync")

    def test_inventory_sync_task_has_target(self) -> None:
        """Assert inventory-sync task data contains a target."""
        task = next(t for t in SYSTEM_TASKS if t.name == "inventory-sync")
        assert task.data.get("target") == "local"

    def test_inventory_sync_task_is_protected(self) -> None:
        """Assert inventory-sync task is protected."""
        task = next(t for t in SYSTEM_TASKS if t.name == "inventory-sync")
        assert task.protected is True

    def test_inventory_sync_task_name_matches_constant(self) -> None:
        """Assert seed task name matches INVENTORY_SYNC_TASK_NAME constant."""
        task = next(t for t in SYSTEM_TASKS if t.name == INVENTORY_SYNC_TASK_NAME)
        assert task.name == INVENTORY_SYNC_TASK_NAME


class TestStalenessTemplateShape:
    """Test the staleness preamble injection across all Nomad templates."""

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_STALENESS)
    def test_meta_optional_contains_staleness_keys(self, template) -> None:
        """Assert ``MetaOptional`` declares both new staleness meta keys."""
        meta_optional = template["ParameterizedJob"]["MetaOptional"]
        assert "scheduled_at" in meta_optional
        assert "staleness_threshold_seconds" in meta_optional

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_STALENESS)
    def test_check_staleness_task_is_first(self, template) -> None:
        """Assert the ``check-staleness`` prestart task is first in the group."""
        tasks = template["TaskGroups"][0]["Tasks"]
        first = tasks[0]
        assert first["Name"] == "check-staleness"
        assert first["Lifecycle"] == {"hook": "prestart", "sidecar": False}
        assert first["Config"]["command"] == "sh"
        assert first["RestartPolicy"] == {"Attempts": 0, "Mode": "fail"}

    @pytest.mark.parametrize("template", PYTHON_TEMPLATES_WITH_PREPARE_ENV)
    def test_prepare_env_is_guarded_by_preamble(self, template) -> None:
        """Assert ``prepare-env`` prepends the staleness preamble to its command."""
        prepare_env = next(
            t for t in template["TaskGroups"][0]["Tasks"] if t["Name"] == "prepare-env"
        )
        script = prepare_env["Config"]["args"][1]
        assert script.startswith(STALENESS_PREAMBLE_SHELL)


class TestStalenessPreambleShell:
    """Test the POSIX ``sh`` preamble string by executing it under ``/bin/sh``."""

    def _run(self, env: dict[str, str]) -> subprocess.CompletedProcess:
        full_env = {"PATH": "/usr/bin:/bin", **env}
        return subprocess.run(
            ["/bin/sh", "-c", STALENESS_PREAMBLE_SHELL],
            env=full_env,
            capture_output=True,
            check=False,
        )

    def test_exit_75_when_elapsed_exceeds_threshold(self) -> None:
        """Assert the preamble exits ``75`` when elapsed exceeds threshold."""
        result = self._run(
            {
                "NOMAD_META_scheduled_at": str(
                    int(time.time()) - STALE_ELAPSED_SECONDS
                ),
                "NOMAD_META_staleness_threshold_seconds": "3600",
            }
        )
        assert result.returncode == STALE_EXIT_CODE
        assert b"SEP_STALE_SKIP" in result.stdout

    def test_exit_0_when_fresh(self) -> None:
        """Assert the preamble exits ``0`` for a fresh dispatch."""
        result = self._run(
            {
                "NOMAD_META_scheduled_at": str(
                    int(time.time()) - FRESH_ELAPSED_SECONDS
                ),
                "NOMAD_META_staleness_threshold_seconds": "3600",
            }
        )
        assert result.returncode == 0
        assert result.stdout == b""

    def test_exit_0_when_scheduled_at_missing(self) -> None:
        """Assert a missing ``scheduled_at`` meta key is a no-op."""
        result = self._run({"NOMAD_META_staleness_threshold_seconds": "3600"})
        assert result.returncode == 0

    def test_exit_0_when_threshold_missing(self) -> None:
        """Assert a missing threshold meta key is a no-op."""
        result = self._run({"NOMAD_META_scheduled_at": "1000"})
        assert result.returncode == 0

    def test_exit_0_when_scheduled_at_in_future(self) -> None:
        """Assert a future ``scheduled_at`` (negative elapsed) is not stale."""
        result = self._run(
            {
                "NOMAD_META_scheduled_at": str(int(time.time()) + 100),
                "NOMAD_META_staleness_threshold_seconds": "3600",
            }
        )
        assert result.returncode == 0

    def test_no_unbraced_nomad_unknown_references(self) -> None:
        """Assert the preamble has no ``${...}`` references Nomad cannot resolve.

        Nomad interpolates ``${...}`` in raw_exec args via its own variable table
        before spawning the shell. Any reference not known to Nomad (e.g. a shell
        local like ``${elapsed}``) fails Nomad config validation and aborts the
        whole task. Shell locals must therefore be referenced with the bareword
        form ``$name`` so Nomad passes them through verbatim to ``/bin/sh``.
        """
        assert "${elapsed}" not in STALENESS_PREAMBLE_SHELL
        assert "${NOMAD_META_staleness_threshold_seconds}" not in (
            STALENESS_PREAMBLE_SHELL
        )

    def test_stale_skip_line_format(self) -> None:
        """Assert the SEP_STALE_SKIP line renders with concrete threshold value.

        Uses a past ``NOMAD_META_scheduled_at`` (1970) against a 5-second
        threshold so elapsed > threshold, and checks the rendered line begins
        with ``SEP_STALE_SKIP: elapsed=`` and contains ``threshold=5s``.
        """
        result = subprocess.run(
            ["/bin/sh", "-c", STALENESS_PREAMBLE_SHELL],
            env={
                "PATH": "/usr/bin:/bin",
                "NOMAD_META_scheduled_at": "100",
                "NOMAD_META_staleness_threshold_seconds": "5",
            },
            capture_output=True,
            check=False,
        )
        assert result.returncode == STALE_EXIT_CODE
        line = result.stdout.decode().strip()
        assert line.startswith("SEP_STALE_SKIP: elapsed=")
        assert "threshold=5s" in line


def test_internal_task_names_membership_is_exact() -> None:
    """Assert INTERNAL_TASK_NAMES holds exactly the three maintenance-task constants.

    Locks the dashboard ``exclude_internal`` filter's scope: adding or removing a
    name (e.g. leaking a generic root task like ``run-python``) fails here, forcing
    a deliberate update instead of silent filter drift.
    """
    assert (
        frozenset(
            {
                INVENTORY_SYNC_TASK_NAME,
                SYNC_RUNNING_TASKS_TASK_NAME,
                CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
            }
        )
        == INTERNAL_TASK_NAMES
    )


def test_internal_task_names_are_all_seeded() -> None:
    """Assert every INTERNAL_TASK_NAMES member is seeded (guards filter/seeder drift)."""
    seeded = {t.name for t in SYSTEM_TASKS}
    seeded |= {e.name for _sched, tasks in SYSTEM_PERIODIC_TASKS for e in tasks}
    expected = set(INTERNAL_TASK_NAMES)
    # check_nomad_cert_expiry periodic task is config-gated; drop it when disabled.
    if tasks_settings.NOMAD.check_cert_expiry_interval is None:
        expected.discard(CHECK_NOMAD_CERT_EXPIRY_TASK_NAME)
    assert expected <= seeded


def test_nomad_cert_expiry_periodic_task_seeded() -> None:
    """Assert tasks__check_nomad_cert_expiry schedule matches TASKS.NOMAD when enabled."""
    interval = tasks_settings.NOMAD.check_cert_expiry_interval
    if interval is None:
        assert not any(
            entry.name == "tasks__check_nomad_cert_expiry"
            for _sched, tasks in SYSTEM_PERIODIC_TASKS
            for entry in tasks
        )
        return
    assert any(
        entry.name == "tasks__check_nomad_cert_expiry"
        and entry.task_name == "app.tasks.celery.check_nomad_cert_expiry"
        for _schedule, tasks in SYSTEM_PERIODIC_TASKS
        for entry in tasks
    )
    for schedule, tasks in SYSTEM_PERIODIC_TASKS:
        for entry in tasks:
            if entry.name == "tasks__check_nomad_cert_expiry":
                assert schedule == interval
                assert entry.task_name == "app.tasks.celery.check_nomad_cert_expiry"
                return
    raise AssertionError("tasks__check_nomad_cert_expiry task not found")


def test_purge_task_history_logs_periodic_task_seeded() -> None:
    """Assert the log-purge periodic task is seeded on the configured schedule."""
    interval = tasks_settings.LOG_PURGE_INTERVAL
    if interval is None:
        assert not any(
            entry.name == "tasks__purge_task_history_logs"
            for _sched, tasks in SYSTEM_PERIODIC_TASKS
            for entry in tasks
        )
        return
    for schedule, tasks in SYSTEM_PERIODIC_TASKS:
        for entry in tasks:
            if entry.name == "tasks__purge_task_history_logs":
                assert schedule == interval
                assert entry.task_name == "app.tasks.celery.purge_task_history_logs"
                return
    raise AssertionError("tasks__purge_task_history_logs task not found")
