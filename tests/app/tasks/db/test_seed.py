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

from app.tasks.db.seed import (
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
    NOMAD_RUN_COMMAND,
    NOMAD_RUN_PYTHON,
    STALENESS_PREAMBLE_SHELL,
    SYSTEM_TASKS,
)
from app.tasks.models import TaskBackendEnum

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
