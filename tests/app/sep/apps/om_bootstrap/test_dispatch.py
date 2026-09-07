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
from unittest.mock import AsyncMock, patch

import pytest

from app.sep.apps.om_bootstrap import dispatch
from app.sep.apps.om_bootstrap.strategy import StepAction


class TestBuildStepScript:
    """Assert both action shapes strategies produce render into one valid script."""

    def test_renders_a_shell_wrapped_command(self) -> None:
        """An ["sh", "-c", ...] action nests correctly inside the outer script."""
        script = dispatch.build_step_script(
            StepAction(command=["sh", "-c", "echo hi && echo bye"])
        )

        assert script == "#!/bin/sh\nset -eu\nsh -c 'echo hi && echo bye'\n"

    def test_renders_a_plain_argv_command(self) -> None:
        """A plain argv action (no shell wrapper) renders as one quoted line."""
        script = dispatch.build_step_script(
            StepAction(command=["systemctl", "enable", "--now", "mongod"])
        )

        assert script == "#!/bin/sh\nset -eu\nsystemctl enable --now mongod\n"

    def test_quotes_arguments_containing_spaces(self) -> None:
        """An argument with a space does not silently become two arguments."""
        script = dispatch.build_step_script(StepAction(command=["echo", "two words"]))

        assert "echo 'two words'" in script


class TestStepScriptFilename:
    """Assert the filename is deterministic and stable across retries."""

    def test_same_inputs_produce_the_same_filename(self) -> None:
        """A retried step overwrites its own script rather than accumulating files."""
        first = dispatch.step_script_filename("run-1", "node00", "pre_check")
        second = dispatch.step_script_filename("run-1", "node00", "pre_check")

        assert first == second

    def test_different_steps_produce_different_filenames(self) -> None:
        """Two steps for the same host never collide on one filename."""
        assert dispatch.step_script_filename(
            "run-1", "node00", "pre_check"
        ) != dispatch.step_script_filename("run-1", "node00", "install_package")


class TestWriteAndCleanupStepScript:
    """Assert the scratch-file lifecycle: written, readable, then removable."""

    def test_write_then_cleanup_round_trip(self) -> None:
        """A written script is readable at the scratch dir, then gone after cleanup."""
        action = StepAction(command=["true"])
        run_id, host, step_name = "run-test", "node00", "verify"

        path, digest = dispatch.write_step_script(run_id, host, step_name, action)
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

    def test_cleanup_of_a_never_written_script_does_not_raise(self) -> None:
        """Cleanup is best-effort -- an already-gone (or never-written) file is fine."""
        dispatch.cleanup_step_script("no-such-run", "node00", "verify")


FAKE_TASK_HISTORY_ID = 7


class TestDispatchStep:
    """Assert dispatch_step writes the script and posts the right Tasks API meta."""

    async def _dispatch(
        self, action: StepAction, *, task_id: int | None = FAKE_TASK_HISTORY_ID
    ) -> tuple[int, AsyncMock]:
        tasks_api = AsyncMock()
        with (
            patch(
                "app.sep.apps.om_bootstrap.dispatch.build_artifact_download_url",
                return_value="https://sep.example/artifacts/download/tok",
            ),
            patch(
                "app.sep.apps.om_bootstrap.dispatch.post_task_execution",
                AsyncMock(return_value=task_id),
            ) as post,
        ):
            result = await dispatch.dispatch_step(
                tasks_api, None, "run-1", "node00", "install_package", action
            )
        return result, post

    @pytest.mark.asyncio
    async def test_returns_the_task_history_id(self) -> None:
        """The id the Tasks API hands back is what the caller gets."""
        result, _post = await self._dispatch(StepAction(command=["true"]))

        assert result == FAKE_TASK_HISTORY_ID

    @pytest.mark.asyncio
    async def test_posts_with_the_root_interpreter(self) -> None:
        """The dispatch actually asks for root -- not the Nomad agent's own user."""
        _result, post = await self._dispatch(StepAction(command=["true"]))

        _tasks_api, task_name, meta = post.call_args.args
        assert task_name == dispatch.EXEC_ARTIFACT_TASK
        assert meta.interpreter == dispatch.ROOT_INTERPRETER
        assert meta.target == "node00"

    @pytest.mark.asyncio
    async def test_raises_when_the_tasks_api_returns_no_id(self) -> None:
        """An accepted-but-id-less dispatch is a Tasks API contract violation, not silent."""
        with pytest.raises(RuntimeError, match="did not return a task history id"):
            await self._dispatch(StepAction(command=["true"]), task_id=None)
