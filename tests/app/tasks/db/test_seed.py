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
import re
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy_celery_beat.models import Period, PeriodicTask

import app.tasks.db.seed as seed_module
from app.core.celery.models import IntervalSchedule
from app.tasks.config import tasks_settings
from app.tasks.db.seed import (
    _CHECK_STALENESS_TASK,
    _launch_check_shell,
    _LOG_CAPTURE_HOLD_TASK,
    EFFECTIVE_INTERPRETER_PATH,
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
from app.tasks.execution.executors.nomad.steps import (
    LAUNCH_CHECK_EXIT_CODE,
    NomadStep,
)
from app.tasks.models import (
    INTERNAL_TASK_NAMES,
    INVENTORY_COLLECTION_TASK_NAME,
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
# Every template that interpolates a launch command from meta. ``run-python``
# is absent: it runs the venv interpreter ``prepare-env`` built, from a payload.
NOMAD_TEMPLATES_WITH_LAUNCH_CHECK = [
    NOMAD_RUN_COMMAND,
    NOMAD_EXEC_ARTIFACT,
    NOMAD_EXEC_PYTHON_ARTIFACT,
]
# The subset whose ``run-script`` launches from the effective interpreter, which
# is what makes stripping a redundant ``sudo`` prefix observable.
ARTIFACT_TEMPLATES_WITH_STRIP = [NOMAD_EXEC_ARTIFACT, NOMAD_EXEC_PYTHON_ARTIFACT]
STALE_EXIT_CODE = 75
# Generous next to the sub-second release measured against live Nomad, but far
# below the 30 s deadline these tests spawn the hold with.
SIGNAL_RESPONSE_BUDGET_SECONDS = 5
STALE_ELAPSED_SECONDS = 7200
FRESH_ELAPSED_SECONDS = 1
ROOT_UID = 0
UNPRIVILEGED_UID = 1000
# Commands the stubbed node resolves. ``postgres`` is deliberately absent, so a
# rule that resolved ``sudo -u postgres <cmd>``'s option *value* would abort an
# invocation that runs; ``nosuchinterp`` is never provided.
RESOLVABLE_ON_NODE = ("bash", "python3", "psql")
#: Executor-node shapes the check must tell apart, as (task uid, ``sudo`` present).
NODE_SHAPES = {
    "root-no-sudo": (ROOT_UID, False),
    "root-sudo": (ROOT_UID, True),
    "user-no-sudo": (UNPRIVILEGED_UID, False),
    "user-sudo": (UNPRIVILEGED_UID, True),
}
#: The two launch-check variants the seeded specs build, as (meta key, strip policy).
LAUNCH_CHECK_VARIANTS = {
    "artifact": ("interpreter", True),
    "command": ("command", False),
}


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


class TestArtifactLauncher:
    """Cover the artifact specs launching from the effective interpreter.

    Both launchers now read a file the ``check-launchable`` step writes, so the
    step is load-bearing for every artifact execution rather than only failing
    ones. These tests execute the launcher strings under ``/bin/sh``.
    """

    def _payload(self, task_dir: Path) -> None:
        """Write a payload script that echoes its own argv, one entry per line."""
        script = task_dir / "script"
        script.write_text('#!/bin/sh\nfor a in "$@"; do echo "$a"; done\n')
        script.chmod(0o755)
        (task_dir / "args_file").write_text("alpha\nbeta gamma\n")

    def _launcher(self, template: dict) -> str:
        """Return the template's ``run-script`` shell string."""
        run_script = next(
            task
            for task in template["TaskGroups"][0]["Tasks"]
            if task["Name"] == NomadStep.RUN_SCRIPT
        )
        assert run_script["Config"]["command"] == "sh"
        return run_script["Config"]["args"][1]

    def _run(
        self,
        script: str,
        *,
        task_dir: Path,
        alloc_dir: Path,
        env: dict[str, str],
        path: str = "/usr/bin:/bin",
    ) -> subprocess.CompletedProcess:
        """Run a launcher string with Nomad's directory references resolved."""
        resolved = script.replace("${NOMAD_TASK_DIR}", str(task_dir)).replace(
            "${NOMAD_ALLOC_DIR}", str(alloc_dir)
        )
        return subprocess.run(
            ["/bin/sh", "-c", resolved],
            env={"PATH": path, **env},
            capture_output=True,
            check=False,
        )

    def test_passes_the_same_argv_as_a_direct_xargs_exec(self, tmp_path: Path) -> None:
        """Assert wrapping the launcher in ``sh -c`` did not reshape the argv.

        ``beta gamma`` must still reach the payload as two arguments. This is
        the regression the rewrite could plausibly introduce, and the only
        thing that covers it.
        """
        task_dir = tmp_path / "local"
        task_dir.mkdir()
        alloc_dir = tmp_path / "alloc"
        alloc_dir.mkdir()
        self._payload(task_dir)

        rewritten = self._run(
            self._launcher(NOMAD_EXEC_ARTIFACT),
            task_dir=task_dir,
            alloc_dir=alloc_dir,
            env={"NOMAD_META_interpreter": "sh"},
        )
        direct = subprocess.run(
            [
                "xargs",
                "--arg-file",
                str(task_dir / "args_file"),
                "env",
                "-S",
                "sh",
                str(task_dir / "script"),
            ],
            env={"PATH": "/usr/bin:/bin"},
            capture_output=True,
            check=False,
        )

        assert rewritten.returncode == 0, rewritten.stderr
        assert direct.returncode == 0, direct.stderr
        assert rewritten.stdout == direct.stdout
        assert rewritten.stdout.decode().split() == ["alpha", "beta", "gamma"]

    def test_launches_from_the_effective_interpreter_when_written(
        self, tmp_path: Path
    ) -> None:
        """Assert a stripped interpreter, not the raw meta, reaches the payload.

        The meta still carries the ``sudo`` prefix the check dropped, so a
        launcher that ignored the handoff file would fail on the node the strip
        exists for.
        """
        task_dir = tmp_path / "local"
        task_dir.mkdir()
        alloc_dir = tmp_path / "alloc"
        alloc_dir.mkdir()
        self._payload(task_dir)
        (alloc_dir / "sep_interpreter").write_text("sh")

        result = self._run(
            self._launcher(NOMAD_EXEC_ARTIFACT),
            task_dir=task_dir,
            alloc_dir=alloc_dir,
            env={"NOMAD_META_interpreter": "sudo sh"},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.decode().split() == ["alpha", "beta", "gamma"]

    def test_falls_back_to_the_meta_when_the_handoff_is_missing(
        self, tmp_path: Path
    ) -> None:
        """Assert a missing handoff file leaves behaviour exactly as it was.

        Without the fallback an absent or empty file would make ``env -S ""``
        exec the *script* as the interpreter.
        """
        task_dir = tmp_path / "local"
        task_dir.mkdir()
        alloc_dir = tmp_path / "alloc"
        alloc_dir.mkdir()
        self._payload(task_dir)

        result = self._run(
            self._launcher(NOMAD_EXEC_ARTIFACT),
            task_dir=task_dir,
            alloc_dir=alloc_dir,
            env={"NOMAD_META_interpreter": "sh"},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.decode().split() == ["alpha", "beta", "gamma"]

    def test_falls_back_when_the_handoff_is_empty(self, tmp_path: Path) -> None:
        """Assert an empty handoff file is treated as no handoff at all."""
        task_dir = tmp_path / "local"
        task_dir.mkdir()
        alloc_dir = tmp_path / "alloc"
        alloc_dir.mkdir()
        self._payload(task_dir)
        (alloc_dir / "sep_interpreter").write_text("")

        result = self._run(
            self._launcher(NOMAD_EXEC_ARTIFACT),
            task_dir=task_dir,
            alloc_dir=alloc_dir,
            env={"NOMAD_META_interpreter": "sh"},
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout.decode().split() == ["alpha", "beta", "gamma"]

    @pytest.mark.parametrize(
        ("effective", "expect_sudo"),
        [("python3", False), ("sudo python3", True)],
    )
    def test_python_launcher_reads_sudo_from_the_effective_interpreter(
        self, tmp_path: Path, effective: str, expect_sudo: str
    ) -> None:
        """Assert the venv python is prefixed from the handoff, not the meta.

        On a stripped root allocation the meta still says ``sudo python3`` while
        the effective interpreter says ``python3``; reading the meta would
        re-introduce the prefix the check just removed.
        """
        task_dir = tmp_path / "local"
        task_dir.mkdir()
        alloc_dir = tmp_path / "alloc"
        (alloc_dir / "venv" / "bin").mkdir(parents=True)
        self._payload(task_dir)
        venv_python = alloc_dir / "venv" / "bin" / "python3"
        venv_python.write_text('#!/bin/sh\necho "python:$*"\n')
        venv_python.chmod(0o755)
        (alloc_dir / "sep_interpreter").write_text(effective)
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        sudo_stub = bin_dir / "sudo"
        sudo_stub.write_text('#!/bin/sh\necho "sudo-used"\nexec "$@"\n')
        sudo_stub.chmod(0o755)

        result = self._run(
            self._launcher(NOMAD_EXEC_PYTHON_ARTIFACT),
            task_dir=task_dir,
            alloc_dir=alloc_dir,
            env={"NOMAD_META_interpreter": "sudo python3"},
            path=f"{bin_dir}:/usr/bin:/bin",
        )

        assert result.returncode == 0, result.stderr
        assert (b"sudo-used" in result.stdout) is expect_sudo
        assert b"python:" in result.stdout


class TestLaunchCheckTemplateShape:
    """Cover the launch-check task's injection across the Nomad templates."""

    def _check_task(self, template: dict) -> dict | None:
        """Return the template's launch-check task, or ``None`` when absent."""
        return next(
            (
                task
                for task in template["TaskGroups"][0]["Tasks"]
                if task["Name"] == NomadStep.CHECK_LAUNCHABLE
            ),
            None,
        )

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_LAUNCH_CHECK)
    def test_check_is_a_non_sidecar_prestart_task(self, template) -> None:
        """Assert the check runs, and can abort the allocation, before the payload."""
        check = self._check_task(template)

        assert check is not None
        assert check["Lifecycle"] == {"hook": "prestart", "sidecar": False}
        assert check["Driver"] == "raw_exec"
        assert check["Config"]["command"] == "sh"
        assert check["RestartPolicy"] == {"Attempts": 0, "Mode": "fail"}

    def test_run_python_has_no_check(self) -> None:
        """Assert the payload-driven spec is left alone.

        ``run-python`` declares no launch-command meta -- it runs the venv
        interpreter it built -- so there is no command chain to resolve.
        """
        assert self._check_task(NOMAD_RUN_PYTHON) is None

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_LAUNCH_CHECK)
    def test_check_reads_the_template_own_launch_meta(
        self, template, tmp_path: Path
    ) -> None:
        """Assert each spec's check resolves the meta key that spec launches.

        Executed rather than pattern-matched against the built string: a check
        wired to the wrong meta key reads an unset variable, which short-circuits
        to a silent pass on every input -- the failure mode a substring
        assertion would report as healthy.
        """
        meta_key = "command" if template is NOMAD_RUN_COMMAND else "interpreter"
        script = self._check_task(template)["Config"]["args"][1]

        def run(env: dict[str, str]) -> int:
            return subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    script.replace(EFFECTIVE_INTERPRETER_PATH, "/dev/null"),
                ],
                env={"PATH": "/usr/bin:/bin", "NOMAD_META_target": "node-1", **env},
                capture_output=True,
                check=False,
            ).returncode

        assert run({f"NOMAD_META_{meta_key}": "nosuchinterp"}) == LAUNCH_CHECK_EXIT_CODE
        other = "interpreter" if meta_key == "command" else "command"
        assert run({f"NOMAD_META_{other}": "nosuchinterp"}) == 0

    @pytest.mark.parametrize("template", ARTIFACT_TEMPLATES_WITH_STRIP)
    def test_artifact_checks_hand_the_interpreter_forward(self, template) -> None:
        """Assert the artifact specs' checks write the effective interpreter."""
        script = self._check_task(template)["Config"]["args"][1]

        assert EFFECTIVE_INTERPRETER_PATH in script

    def test_run_command_check_writes_nothing(self) -> None:
        """Assert the abort-only check leaves no handoff file behind.

        ``run-command``'s launcher reads its meta directly, so a file written
        here would never be read -- and its meta carries no SEP-applied ``sudo``
        prefix to strip in the first place.
        """
        script = self._check_task(NOMAD_RUN_COMMAND)["Config"]["args"][1]

        assert EFFECTIVE_INTERPRETER_PATH not in script

    @pytest.mark.parametrize("template", NOMAD_TEMPLATES_WITH_LAUNCH_CHECK)
    def test_check_task_is_not_shared_between_templates(self, template) -> None:
        """Assert each template holds its own check rather than a shared dict.

        The templates are module-level mutables Nomad job registration reads;
        one shared dict would let a per-template edit leak across all three.
        """
        checks = [
            task
            for task in template["TaskGroups"][0]["Tasks"]
            if task["Name"] == NomadStep.CHECK_LAUNCHABLE
        ]

        assert len(checks) == 1
        others = [
            self._check_task(other)
            for other in NOMAD_TEMPLATES_WITH_LAUNCH_CHECK
            if other is not template
        ]
        assert all(checks[0] is not other for other in others)


class TestLaunchCheckShell:
    """Execute the launch-check preamble under ``/bin/sh`` on a stubbed node.

    ``id`` is stubbed on ``PATH`` rather than acquiring a real uid 0. The two
    were measured to agree on every row below, and a stub needs no user
    namespace, which CI runners do not uniformly provide.
    """

    def _node(self, tmp_path: Path, node: str) -> Path:
        """Build the stub ``PATH`` directory standing in for the executor node."""
        uid, has_sudo = NODE_SHAPES[node]
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir(exist_ok=True)
        stubs = {"id": f"#!/bin/sh\necho {uid}\n"}
        for name in RESOLVABLE_ON_NODE:
            stubs[name] = "#!/bin/sh\nexit 0\n"
        if has_sudo:
            stubs["sudo"] = "#!/bin/sh\nexit 0\n"
        for name, body in stubs.items():
            stub = bin_dir / name
            stub.write_text(body)
            stub.chmod(0o755)
        return bin_dir

    def _run(
        self,
        tmp_path: Path,
        *,
        node: str,
        meta: str,
        variant: str = "artifact",
    ) -> tuple[subprocess.CompletedProcess, Path]:
        """Run the built preamble; return the process and the handoff file."""
        bin_dir = self._node(tmp_path, node)
        meta_key, allow_strip = LAUNCH_CHECK_VARIANTS[variant]
        alloc_dir = tmp_path / "alloc"
        alloc_dir.mkdir(exist_ok=True)
        handoff = alloc_dir / "sep_interpreter"
        script = _launch_check_shell(meta_key, allow_strip=allow_strip).replace(
            EFFECTIVE_INTERPRETER_PATH, str(handoff)
        )
        result = subprocess.run(
            ["/bin/sh", "-c", script],
            env={
                "PATH": str(bin_dir),
                f"NOMAD_META_{meta_key}": meta,
                "NOMAD_META_target": "node-1",
            },
            capture_output=True,
            check=False,
            cwd=tmp_path,
        )
        return result, handoff

    @pytest.mark.parametrize(
        ("node", "meta", "expected_exit", "expected_effective"),
        [
            ("root-no-sudo", "sudo bash", 0, "bash"),
            ("root-no-sudo", "sudo python3", 0, "python3"),
            ("root-no-sudo", "sudo nosuchinterp", LAUNCH_CHECK_EXIT_CODE, None),
            ("root-no-sudo", "sudo -u postgres bash", LAUNCH_CHECK_EXIT_CODE, None),
            ("root-no-sudo", "sudo FOO=1 bash", LAUNCH_CHECK_EXIT_CODE, None),
            ("root-sudo", "sudo bash", 0, "sudo bash"),
            ("user-no-sudo", "sudo bash", LAUNCH_CHECK_EXIT_CODE, None),
            ("user-sudo", "sudo bash", 0, "sudo bash"),
            (
                "user-sudo",
                "sudo -u postgres nosuchinterp",
                LAUNCH_CHECK_EXIT_CODE,
                None,
            ),
            ("user-sudo", "sudo -u postgres psql", 0, "sudo -u postgres psql"),
            ("user-no-sudo", "bash", 0, "bash"),
            ("user-no-sudo", "nosuchinterp", LAUNCH_CHECK_EXIT_CODE, None),
            ("user-no-sudo", "FOO=1 bash", 0, "FOO=1 bash"),
            ("user-no-sudo", "bash -x", 0, "bash -x"),
            ("user-no-sudo", "'/tmp/x/true2'", 0, "'/tmp/x/true2'"),
            ("root-no-sudo", "'/tmp/x/true2'", 0, "'/tmp/x/true2'"),
            (
                "user-no-sudo",
                "env FOO=1 nosuchinterp",
                0,
                "env FOO=1 nosuchinterp",
            ),
            ("user-no-sudo", "g/ba*", LAUNCH_CHECK_EXIT_CODE, None),
        ],
    )
    def test_resolves_the_launch_chain(
        self,
        tmp_path: Path,
        node: str,
        meta: str,
        expected_exit: int,
        expected_effective: str | None,
    ) -> None:
        """Assert each node/interpreter pair resolves to its planned outcome."""
        result, handoff = self._run(tmp_path, node=node, meta=meta)

        assert result.returncode == expected_exit, result.stdout + result.stderr
        if expected_effective is None:
            assert not handoff.exists()
        else:
            assert handoff.read_text() == expected_effective

    @pytest.mark.parametrize(
        ("node", "meta", "expected_command"),
        [
            ("root-no-sudo", "sudo nosuchinterp", "nosuchinterp"),
            ("root-no-sudo", "sudo -u postgres bash", "sudo"),
            ("root-no-sudo", "sudo FOO=1 bash", "sudo"),
            ("user-no-sudo", "sudo bash", "sudo"),
            ("user-sudo", "sudo -u postgres nosuchinterp", "nosuchinterp"),
            ("user-no-sudo", "nosuchinterp", "nosuchinterp"),
            ("user-no-sudo", "g/ba*", "g/ba*"),
        ],
    )
    def test_abort_line_names_the_unresolvable_command_and_node(
        self,
        tmp_path: Path,
        node: str,
        meta: str,
        expected_command: str,
    ) -> None:
        """Assert the abort log line carries the failing command and the node.

        That line is the operator's only diagnostic: ``run-script`` never
        starts, so nothing else in the allocation says what could not be found.
        It is asserted as the last line rather than the whole output because a
        strip that happened first legitimately reports itself above it.
        """
        result, _ = self._run(tmp_path, node=node, meta=meta)

        assert result.returncode == LAUNCH_CHECK_EXIT_CODE
        assert (
            result.stdout.decode().splitlines()[-1]
            == f"SEP_UNLAUNCHABLE: command={expected_command} node=node-1"
        )

    def test_strip_announces_itself(self, tmp_path: Path) -> None:
        """Assert a stripped ``sudo`` prefix is reported on the step's stdout."""
        result, _ = self._run(tmp_path, node="root-no-sudo", meta="sudo bash")

        assert result.returncode == 0
        assert result.stdout.decode().strip() == "SEP_SUDO_STRIPPED: node=node-1"

    def test_declines_an_unrecognized_sudo_option_cluster(self, tmp_path: Path) -> None:
        """Assert a bundled short-option cluster is passed through, not aborted.

        ``-nu postgres`` ends in a value-taking option the walker does not
        decompose, so the token after it is not the command. Aborting on that
        guess would fail an invocation that works today.
        """
        result, handoff = self._run(
            tmp_path, node="user-sudo", meta="sudo -nu postgres nosuchinterp"
        )

        assert result.returncode == 0
        assert handoff.read_text() == "sudo -nu postgres nosuchinterp"

    def test_run_command_variant_neither_strips_nor_writes(
        self, tmp_path: Path
    ) -> None:
        """Assert the abort-only variant leaves no handoff file behind.

        ``run-command``'s launcher reads the meta directly, so a handoff file
        would be written and never read.
        """
        result, handoff = self._run(
            tmp_path, node="root-no-sudo", meta="sudo bash", variant="command"
        )

        assert result.returncode == LAUNCH_CHECK_EXIT_CODE
        assert not handoff.exists()

    @pytest.mark.parametrize("variant", sorted(LAUNCH_CHECK_VARIANTS))
    def test_shell_string_parses(self, variant: str) -> None:
        """Assert the concatenated fragments form a syntactically valid script.

        The builder joins fragments, so a dropped ``;`` is otherwise caught only
        when Nomad runs the step.
        """
        meta_key, allow_strip = LAUNCH_CHECK_VARIANTS[variant]
        script = _launch_check_shell(meta_key, allow_strip=allow_strip)

        parsed = subprocess.run(
            ["/bin/sh", "-n", "-c", script], capture_output=True, check=False
        )

        assert parsed.returncode == 0, parsed.stderr

    @pytest.mark.parametrize("variant", sorted(LAUNCH_CHECK_VARIANTS))
    def test_only_brace_reference_is_the_alloc_dir(self, variant: str) -> None:
        """Assert no ``${...}`` reference Nomad cannot resolve reaches the spec.

        Nomad interpolates ``${...}`` through its own variable table before
        spawning the shell and fails config validation on anything it does not
        know, so shell locals must use the bareword form. ``${NOMAD_ALLOC_DIR}``
        is in that table and is the one brace form that is correct here.
        """
        meta_key, allow_strip = LAUNCH_CHECK_VARIANTS[variant]
        script = _launch_check_shell(meta_key, allow_strip=allow_strip)

        assert set(re.findall(r"\$\{[^}]*\}", script)) <= {"${NOMAD_ALLOC_DIR}"}


def test_internal_task_names_membership_is_exact() -> None:
    """Assert INTERNAL_TASK_NAMES holds exactly the maintenance-task constants.

    Locks the dashboard ``exclude_internal`` filter's scope: adding or removing a
    name (e.g. leaking a generic root task like ``run-python``) fails here, forcing
    a deliberate update instead of silent filter drift.
    """
    assert (
        frozenset(
            {
                INVENTORY_SYNC_TASK_NAME,
                INVENTORY_COLLECTION_TASK_NAME,
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


class TestInventoryCollectionTask:
    """Test the inventory-collection system task row."""

    def test_the_task_row_is_always_seeded(self) -> None:
        """Seed the collection ``Task`` row regardless of the schedule.

        The interval decides whether a *schedule* fires, and it lives on the SEP
        side; the task itself must exist either way so an operator can attach a
        schedule from the UI.
        """
        task = next(t for t in SYSTEM_TASKS if t.name == INVENTORY_COLLECTION_TASK_NAME)

        assert task.data["callable"] == (
            "app.sep.apps.inventory.collection.run_scheduled_inventory_collection"
        )
        assert task.protected is True
