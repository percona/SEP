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

"""Assert step scripts render correctly and dispatch reaches the Tasks API right."""

import hashlib
import shutil
import stat
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from app.extensions.apps.om_bootstrap import dispatch
from app.extensions.apps.om_bootstrap.strategy import StepAction

#: What coreutils ``timeout`` exits with when it had to stop the command.
TIMED_OUT_EXIT = 124
#: Owner read/write only — a step script can carry a secret.
PRIVATE_FILE_MODE = 0o600
#: Owner-only access to the scratch directory holding those scripts.
PRIVATE_DIR_MODE = 0o700


def _preamble(timeout_s: int) -> str:
    """Return the fixed head every step script starts with."""
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        'if [ -z "${OM_BOOTSTRAP_STEP_TIMED:-}" ]; then\n'
        "  export OM_BOOTSTRAP_STEP_TIMED=1\n"
        f'  exec timeout --kill-after=10 {timeout_s} sh "$0"\n'
        "fi\n"
    )


class TestBuildStepScript:
    """Assert both action shapes strategies produce render into one valid script."""

    def test_renders_a_shell_wrapped_command_as_the_script_body(self) -> None:
        """Write an ["sh", "-c", body] action's body as the script, not a nested sh -c.

        A nested ``sh -c`` would carry the body — and any secret in it — in
        its argv, visible in ``ps``.
        """
        script = dispatch.build_step_script(
            StepAction(command=["sh", "-c", "echo hi && echo bye"], timeout_s=30)
        )

        assert script == _preamble(30) + "echo hi && echo bye\n"

    def test_renders_a_plain_argv_command(self) -> None:
        """Render a plain argv action (no shell wrapper) as one quoted line."""
        script = dispatch.build_step_script(
            StepAction(command=["systemctl", "enable", "--now", "mongod"])
        )

        assert script == _preamble(120) + "systemctl enable --now mongod\n"

    @pytest.mark.skipif(shutil.which("timeout") is None, reason="needs coreutils")
    def test_enforces_the_action_timeout(self, tmp_path: Path) -> None:
        """Kill a step that overruns timeout_s, exiting 124 instead of hanging."""
        script = tmp_path / "step.sh"
        script.write_text(
            dispatch.build_step_script(
                StepAction(command=["sh", "-c", "sleep 5"], timeout_s=1)
            )
        )

        result = subprocess.run(
            ["sh", str(script)], capture_output=True, timeout=30, check=False
        )

        assert result.returncode == TIMED_OUT_EXIT

    def test_runs_the_body_once_under_the_timeout(self, tmp_path: Path) -> None:
        """Run the body once on the re-executed pass instead of wrapping again."""
        script = tmp_path / "step.sh"
        script.write_text(
            dispatch.build_step_script(StepAction(command=["echo", "ran"]))
        )

        result = subprocess.run(
            ["sh", str(script)], capture_output=True, text=True, timeout=30, check=True
        )

        assert result.stdout == "ran\n"

    def test_quotes_arguments_containing_spaces(self) -> None:
        """Keep an argument with a space as one argument, not two."""
        script = dispatch.build_step_script(StepAction(command=["echo", "two words"]))

        assert "echo 'two words'" in script


class TestStepScriptFilename:
    """Assert the filename is deterministic and stable across retries."""

    def test_same_inputs_produce_the_same_filename(self) -> None:
        """Overwrite a retried step's own script rather than accumulating files."""
        first = dispatch.step_script_filename("run-1", "node00", "pre_check")
        second = dispatch.step_script_filename("run-1", "node00", "pre_check")

        assert first == second

    def test_different_steps_produce_different_filenames(self) -> None:
        """Give two steps for the same host distinct filenames."""
        assert dispatch.step_script_filename(
            "run-1", "node00", "pre_check"
        ) != dispatch.step_script_filename("run-1", "node00", "install_package")


class TestWriteAndCleanupStepScript:
    """Assert the scratch-file lifecycle: written, readable, then removable."""

    @pytest.mark.asyncio
    async def test_write_then_cleanup_round_trip(self) -> None:
        """Keep a written script in the scratch dir until cleanup removes it."""
        action = StepAction(command=["true"])
        run_id, host, step_name = "run-test", "node00", "verify"

        path, digest = await dispatch.write_step_script(run_id, host, step_name, action)
        try:
            content = path.read_text()
            assert content == dispatch.build_step_script(action)
            assert (
                digest
                == hashlib.md5(content.encode(), usedforsecurity=False).hexdigest()
            )
            assert path.parent == dispatch.step_scripts_dir()
        finally:
            dispatch.cleanup_step_script(run_id, host, step_name)

        assert not path.exists()

    @pytest.mark.asyncio
    async def test_script_is_private_to_its_owner(self) -> None:
        """Keep a script, which can carry a secret, 0600 in a 0700 directory."""
        run_id, host, step_name = "run-perms", "node00", "verify"

        path, _digest = await dispatch.write_step_script(
            run_id, host, step_name, StepAction(command=["true"])
        )
        try:
            assert stat.S_IMODE(path.stat().st_mode) == PRIVATE_FILE_MODE
            assert stat.S_IMODE(path.parent.stat().st_mode) == PRIVATE_DIR_MODE
        finally:
            dispatch.cleanup_step_script(run_id, host, step_name)

    @pytest.mark.asyncio
    async def test_rewrite_tightens_a_pre_existing_script(self) -> None:
        """Tighten an existing, looser file to 0600 when a retry rewrites it."""
        run_id, host, step_name = "run-retry-perms", "node00", "verify"
        path = dispatch.step_scripts_dir() / dispatch.step_script_filename(
            run_id, host, step_name
        )
        path.write_text("stale")
        path.chmod(0o644)

        try:
            await dispatch.write_step_script(
                run_id, host, step_name, StepAction(command=["true"])
            )
            assert stat.S_IMODE(path.stat().st_mode) == PRIVATE_FILE_MODE
        finally:
            dispatch.cleanup_step_script(run_id, host, step_name)

    def test_scripts_dir_is_tightened_when_it_already_exists(self) -> None:
        """Tighten a directory left with looser permissions back to 0700."""
        directory = dispatch.step_scripts_dir()
        directory.chmod(0o755)

        assert (
            stat.S_IMODE(dispatch.step_scripts_dir().stat().st_mode) == PRIVATE_DIR_MODE
        )

    def test_cleanup_of_a_never_written_script_does_not_raise(self) -> None:
        """Clean up best-effort: an already-gone (or never-written) file is fine."""
        dispatch.cleanup_step_script("no-such-run", "node00", "verify")

    @pytest.mark.asyncio
    async def test_cleanup_run_scripts_removes_only_that_runs_scripts(self) -> None:
        """Sweep every script of a finished run, and no other run's."""
        action = StepAction(command=["true"])
        swept = [
            await dispatch.write_step_script("run-sweep", host, step, action)
            for host, step in (("node00", "pre_check"), ("node01", "verify"))
        ]
        kept, _digest = await dispatch.write_step_script(
            "run-other", "node00", "pre_check", action
        )

        try:
            dispatch.cleanup_run_scripts("run-sweep")

            assert not any(path.exists() for path, _digest in swept)
            assert kept.exists()
        finally:
            dispatch.cleanup_step_script("run-other", "node00", "pre_check")


FAKE_TASK_HISTORY_ID = 7


class TestDispatchStep:
    """Assert dispatch_step writes the script and posts the right Tasks API meta."""

    async def _dispatch(
        self,
        action: StepAction,
        *,
        task_id: int | None = FAKE_TASK_HISTORY_ID,
        post_error: Exception | None = None,
    ) -> tuple[int, AsyncMock]:
        tasks_api = AsyncMock()
        with (
            patch(
                "app.extensions.apps.om_bootstrap.dispatch.build_artifact_download_url",
                return_value="https://extensions.example/artifacts/download/tok",
            ),
            patch(
                "app.extensions.apps.om_bootstrap.dispatch.post_task_execution",
                AsyncMock(return_value=task_id, side_effect=post_error),
            ) as post,
        ):
            result = await dispatch.dispatch_step(
                tasks_api, None, "run-1", "node00", "install_package", action
            )
        return result, post

    @pytest.mark.asyncio
    async def test_returns_the_task_history_id(self) -> None:
        """Return the id the Tasks API hands back to the caller."""
        result, _post = await self._dispatch(StepAction(command=["true"]))

        assert result == FAKE_TASK_HISTORY_ID

    @pytest.mark.asyncio
    async def test_posts_with_the_root_interpreter(self) -> None:
        """Ask for root in the dispatch, not the Nomad agent's own user."""
        _result, post = await self._dispatch(StepAction(command=["true"]))

        _tasks_api, task_name, meta = post.call_args.args
        assert task_name == dispatch.EXEC_ARTIFACT_TASK
        assert meta.interpreter == dispatch.ROOT_INTERPRETER
        assert meta.target == "node00"

    @pytest.mark.asyncio
    async def test_raises_when_the_tasks_api_returns_no_id(self) -> None:
        """Raise on an accepted-but-id-less dispatch, a Tasks API contract violation."""
        with pytest.raises(RuntimeError, match="did not return a task history id"):
            await self._dispatch(StepAction(command=["true"]), task_id=None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "post_error",
        [aiohttp.ClientConnectionError("refused"), RuntimeError(), TimeoutError()],
    )
    async def test_removes_the_script_when_the_dispatch_fails(
        self, post_error: Exception
    ) -> None:
        """Remove the script of a failed dispatch, which no executor will download."""
        path = dispatch.step_scripts_dir() / dispatch.step_script_filename(
            "run-1", "node00", "install_package"
        )

        with pytest.raises(type(post_error)):
            await self._dispatch(StepAction(command=["true"]), post_error=post_error)

        assert not path.exists()

    @pytest.mark.asyncio
    async def test_removes_the_script_when_no_history_id_comes_back(self) -> None:
        """Remove the script when the Tasks API returns no history id either."""
        path = dispatch.step_scripts_dir() / dispatch.step_script_filename(
            "run-1", "node00", "install_package"
        )

        with pytest.raises(RuntimeError):
            await self._dispatch(StepAction(command=["true"]), task_id=None)

        assert not path.exists()
