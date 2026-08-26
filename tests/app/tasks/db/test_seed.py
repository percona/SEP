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

import json
import subprocess
import time

import pytest
from sqlalchemy_celery_beat.models import Period, PeriodicTask

import app.tasks.db.seed as seed_module
from app.core.celery.models import IntervalSchedule
from app.tasks.config import tasks_settings
from app.tasks.db.seed import (
    _CHECK_STALENESS_TASK,
    _LOG_CAPTURE_HOLD_TASK,
    LOG_CAPTURE_HOLD_SHELL,
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
    NOMAD_RUN_COMMAND,
    NOMAD_RUN_PYTHON,
    STALENESS_PREAMBLE_SHELL,
    SYSTEM_PERIODIC_TASKS,
    SYSTEM_TASKS,
)
from app.tasks.execution.executors.nomad.constants import (
    CHECK_NOMAD_CERT_EXPIRY_TASK_NAME,
)
from app.tasks.execution.executors.nomad.steps import NomadStep
from app.tasks.models import (
    INTERNAL_TASK_NAMES,
    INVENTORY_SYNC_TASK_NAME,
    SYNC_RUNNING_TASKS_TASK_NAME,
    TaskBackendEnum,
)

PMM_SYNCER = "app.sep.sync.syncers.pmm.PMMSyncer"
MYSQL_SYNCER = "app.sep.sync.syncers.mysql.syncer.MySQLSyncer"
FIFTEEN_MINUTES = IntervalSchedule(every=15, period=Period.MINUTES)

NOMAD_TEMPLATES_WITH_STALENESS = [
    NOMAD_RUN_COMMAND,
    NOMAD_RUN_PYTHON,
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
]
PYTHON_TEMPLATES_WITH_PREPARE_ENV = [NOMAD_RUN_PYTHON, NOMAD_EXEC_PYTHON_ARTIFACT]
STALE_EXIT_CODE = 75
# Generous next to the sub-second release measured against live Nomad, but far
# below the 30 s deadline these tests spawn the hold with.
SIGNAL_RESPONSE_BUDGET_SECONDS = 5
STALE_ELAPSED_SECONDS = 7200
FRESH_ELAPSED_SECONDS = 1


class TestNomadStepNameParity:
    """Assert every Nomad task Name in seed templates is a NomadStep member."""

    def test_every_seed_task_name_is_nomad_step_member(self) -> None:
        """Walk every job-spec template seed.py defines, across all task groups.

        The templates are discovered from the seed module rather than read off a
        hand-maintained list, and every task group is walked rather than the
        first: a guard scoped to a sample reports clean precisely when a new
        template or group is the thing that bypassed the enum.
        """
        templates = [
            value
            for value in vars(seed_module).values()
            if isinstance(value, dict) and "TaskGroups" in value
        ]
        undiscovered = [
            known
            for known in NOMAD_TEMPLATES_WITH_STALENESS
            if not any(known is found for found in templates)
        ]
        assert not undiscovered, "template discovery missed a known NOMAD_* job spec"

        names: list[object] = [_CHECK_STALENESS_TASK["Name"]]
        for template in templates:
            for group in template["TaskGroups"]:
                names.extend(task["Name"] for task in group["Tasks"])

        for name in names:
            assert isinstance(name, NomadStep), f"{name!r} is not a NomadStep"


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


class TestLogCaptureHoldTemplateShape:
    """Cover the log-capture-hold task injection across all Nomad templates."""

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_STALENESS)
    def test_meta_optional_declares_the_hold_key(self, template) -> None:
        """Assert ``MetaOptional`` declares the hold-duration meta key.

        The dispatch-time injection is gated on the key being declared, so a
        template missing it silently falls back to the shell default forever.
        """
        assert (
            "log_capture_hold_seconds" in template["ParameterizedJob"]["MetaOptional"]
        )

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_STALENESS)
    def test_hold_task_is_a_non_sidecar_poststop_task(self, template) -> None:
        """Assert every template carries the hold as a non-sidecar poststop task."""
        hold = next(
            task
            for task in template["TaskGroups"][0]["Tasks"]
            if task["Name"] == NomadStep.LOG_CAPTURE_HOLD
        )
        assert hold["Lifecycle"] == {"hook": "poststop", "sidecar": False}
        assert hold["Driver"] == "raw_exec"
        assert hold["Config"]["command"] == "sh"
        assert hold["RestartPolicy"] == {"Attempts": 0, "Mode": "fail"}

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_STALENESS)
    def test_hold_task_is_not_shared_between_templates(self, template) -> None:
        """Assert each template holds its own copy rather than a shared dict.

        The templates are module-level mutables Nomad job registration reads;
        one shared dict would let a per-template edit leak across all four.
        """
        holds = [
            task
            for task in template["TaskGroups"][0]["Tasks"]
            if task["Name"] == NomadStep.LOG_CAPTURE_HOLD
        ]
        assert len(holds) == 1
        assert holds[0] is not _LOG_CAPTURE_HOLD_TASK


class TestLogCaptureHoldShell:
    """Cover the hold shell string by executing it under ``/bin/sh``."""

    def _spawn(self, env: dict[str, str]) -> subprocess.Popen:
        full_env = {"PATH": "/usr/bin:/bin", **env}
        return subprocess.Popen(
            ["/bin/sh", "-c", LOG_CAPTURE_HOLD_SHELL],
            env=full_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_no_unbraced_nomad_unknown_references(self) -> None:
        """Assert the hold shell uses no ``${...}`` form.

        Nomad interpolates ``${...}`` through its own variable table before the
        shell sees it and fails job validation on names it does not know.
        """
        assert "${" not in LOG_CAPTURE_HOLD_SHELL

    def test_self_exits_at_the_meta_supplied_deadline(self) -> None:
        """Assert the hold terminates on its own once the deadline elapses."""
        process = self._spawn({"NOMAD_META_log_capture_hold_seconds": "1"})
        assert process.wait(timeout=10) == 0

    def test_holds_until_signalled_rather_than_exiting_immediately(self) -> None:
        """Assert a long deadline keeps the step alive until it is signalled."""
        process = self._spawn({"NOMAD_META_log_capture_hold_seconds": "30"})
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        finally:
            process.kill()
            process.wait(timeout=10)

    def test_sigterm_releases_the_hold_promptly(self) -> None:
        """Assert SIGTERM exits ``0`` well before the deadline would elapse.

        A POSIX shell runs traps only between foreground commands, so the
        backgrounded ``sleep`` plus ``wait`` is what makes the signal land at
        all rather than being deferred for the full hold.
        """
        process = self._spawn({"NOMAD_META_log_capture_hold_seconds": "30"})
        time.sleep(0.3)
        started = time.monotonic()
        process.terminate()
        assert process.wait(timeout=10) == 0
        assert time.monotonic() - started < SIGNAL_RESPONSE_BUDGET_SECONDS

    def test_falls_back_to_the_default_when_meta_is_absent(self) -> None:
        """Assert an unset meta key still holds rather than exiting at once.

        A job dispatched by hand carries no meta; without the fallback the
        allocation would be collectable immediately and the defect returns.
        """
        process = self._spawn({})
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        finally:
            process.terminate()
            assert process.wait(timeout=10) == 0

    def test_falls_back_to_the_default_when_meta_is_empty(self) -> None:
        """Assert an empty meta value takes the default rather than ``sleep ""``."""
        process = self._spawn({"NOMAD_META_log_capture_hold_seconds": ""})
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        finally:
            process.terminate()
            assert process.wait(timeout=10) == 0


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


class TestInventorySyncSchedule:
    """Test the default inventory-sync schedule entry builder."""

    def test_returns_none_when_interval_unset(self, mocker) -> None:
        """Assert no entry is built when INVENTORY_SYNC_INTERVAL is unset."""
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", None)

        assert seed_module._inventory_sync_schedule() is None

    def test_builds_entry_pinned_to_the_configured_syncer(self, mocker) -> None:
        """Assert the entry carries the execute-by-name shape and the syncer."""
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", FIFTEEN_MINUTES)
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_SYNCER", PMM_SYNCER)

        schedule = seed_module._inventory_sync_schedule()

        assert schedule is not None
        (entry,) = schedule.tasks
        assert entry.name == seed_module.INVENTORY_SYNC_SCHEDULE_NAME
        assert entry.task_name == "app.tasks.celery.execute_task_by_name"
        assert entry.extra_kwargs is not None
        kwargs = json.loads(entry.extra_kwargs["kwargs"])
        assert kwargs["task_name"] == INVENTORY_SYNC_TASK_NAME
        assert kwargs["periodic_task_name"] == seed_module.INVENTORY_SYNC_SCHEDULE_NAME
        assert kwargs["execution_data"]["meta"]["syncer"] == PMM_SYNCER

    def test_builds_sync_all_entry_when_syncer_unset(self, mocker) -> None:
        """Assert an unset syncer produces kwargs carrying no execution data."""
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", FIFTEEN_MINUTES)
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_SYNCER", None)

        schedule = seed_module._inventory_sync_schedule()

        assert schedule is not None
        (entry,) = schedule.tasks
        assert entry.extra_kwargs is not None
        kwargs = json.loads(entry.extra_kwargs["kwargs"])
        assert kwargs["task_name"] == INVENTORY_SYNC_TASK_NAME
        assert "execution_data" not in kwargs

    def test_entry_uses_the_configured_interval(self, mocker) -> None:
        """Assert the entry is seeded on the configured interval."""
        mocker.patch.object(tasks_settings, "INVENTORY_SYNC_INTERVAL", FIFTEEN_MINUTES)

        schedule = seed_module._inventory_sync_schedule()

        assert schedule is not None
        assert schedule.schedule == FIFTEEN_MINUTES


@pytest.mark.parametrize(
    ("kwargs", "configured_syncer", "expected"),
    [
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": PMM_SYNCER}}}),
            PMM_SYNCER,
            True,
            id="same-syncer-blocks",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": MYSQL_SYNCER}}}),
            PMM_SYNCER,
            False,
            id="other-syncer-does-not-block",
        ),
        pytest.param(
            json.dumps({"task_name": INVENTORY_SYNC_TASK_NAME}),
            PMM_SYNCER,
            True,
            id="sync-all-row-blocks",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": MYSQL_SYNCER}}}),
            None,
            True,
            id="any-row-blocks-a-sync-all-default",
        ),
        pytest.param("", PMM_SYNCER, True, id="empty-kwargs-fails-closed"),
        pytest.param(None, PMM_SYNCER, True, id="null-kwargs-fails-closed"),
        pytest.param("[1, 2]", PMM_SYNCER, True, id="non-object-json-fails-closed"),
        pytest.param("{not json", PMM_SYNCER, True, id="undecodable-fails-closed"),
        pytest.param(
            json.dumps({"execution_data": "not-a-dict"}),
            PMM_SYNCER,
            True,
            id="non-mapping-execution-data-fails-closed",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": "not-a-dict"}}),
            PMM_SYNCER,
            True,
            id="non-mapping-meta-fails-closed",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": ""}}}),
            PMM_SYNCER,
            True,
            id="empty-syncer-means-sync-all",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": {"bad": True}}}}),
            PMM_SYNCER,
            True,
            id="non-string-syncer-fails-closed",
        ),
        pytest.param(
            json.dumps({"execution_data": {"meta": {"syncer": "   "}}}),
            PMM_SYNCER,
            True,
            id="blank-syncer-fails-closed",
        ),
    ],
)
def test_schedule_covers_syncer(
    kwargs: str | None, configured_syncer: str | None, *, expected: bool
) -> None:
    """Assert an existing beat row is judged against the configured syncer."""
    row = PeriodicTask(name="run_inventory-sync_15_minutes", kwargs=kwargs)

    assert seed_module._schedule_covers_syncer(row, configured_syncer) is expected
