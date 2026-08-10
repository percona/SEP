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
"""Cover the wrapper that runs the app-set checker inside a built image."""

import os
import subprocess
from pathlib import Path

import pytest

from tests.sidecar.conftest import SIDECAR_DIR

WRAPPER = SIDECAR_DIR / "verify_image_apps.sh"
CHECKER = SIDECAR_DIR / "verify_image_apps.py"

FAKE_RUNTIME = r"""#!/usr/bin/env bash
printf '%s\n' "$@" > "$FAKE_ARGV"
cat > "$FAKE_STDIN"
printf '%s' "$FAKE_STDOUT"
exit "$FAKE_EXIT"
"""
"""A stand-in for ``docker``/``podman`` that records how it was called."""

DEFAULT_VERDICT = "verified restricted: 2 app packages (framework, shared)"

IMAGE = "sep:HEAD"

USAGE_EXIT_CODE = 2
"""The status the wrapper exits with when its own arguments are wrong."""


class FakeRuntime:
    """Stand in for the container runtime so the wrapper is testable on the host.

    Records the argv and the piped-in script the wrapper hands the runtime, then
    returns a caller-chosen verdict and exit code in the container's place.
    """

    def __init__(self, root: Path, name: str = "fake-runtime"):
        """Write the fake runtime under ``root``.

        :param root: The per-test temporary directory to build in.
        :param name: The executable's filename, which a ``PATH`` lookup matches.
        """
        self.path = root / name
        self.path.write_text(FAKE_RUNTIME, encoding="utf-8")
        self.path.chmod(0o755)
        self._argv_file = root / "argv"
        self._stdin_file = root / "stdin"

    def run(
        self,
        *arguments: str,
        verdict: str = DEFAULT_VERDICT,
        exit_code: int = 0,
        environment: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the wrapper with this fake standing in for the container runtime.

        :param arguments: The wrapper's own arguments.
        :param verdict: What the fake writes to stdout.
        :param exit_code: What the fake exits with.
        :param environment: Overrides applied over the base environment; by
            default ``CONTAINER_RUNTIME`` names this fake by path.
        :return: The completed wrapper run.
        """
        base = {
            "PATH": os.environ["PATH"],
            "FAKE_ARGV": str(self._argv_file),
            "FAKE_STDIN": str(self._stdin_file),
            "FAKE_STDOUT": verdict,
            "FAKE_EXIT": str(exit_code),
        }
        if environment is None:
            environment = {"CONTAINER_RUNTIME": str(self.path)}
        return subprocess.run(
            [str(WRAPPER), *arguments],
            env={**base, **environment},
            capture_output=True,
            text=True,
            check=False,
        )

    @property
    def argv(self) -> list[str]:
        """Return the arguments the wrapper handed the runtime.

        :return: One entry per argument, in the order they were passed.
        """
        return self._argv_file.read_text(encoding="utf-8").splitlines()

    @property
    def stdin(self) -> str:
        """Return the script the wrapper piped into the runtime.

        :return: Everything the runtime received on stdin.
        """
        return self._stdin_file.read_text(encoding="utf-8")


@pytest.fixture
def fake_runtime(tmp_path: Path) -> FakeRuntime:
    """Build a container-runtime stand-in for one test.

    :param tmp_path: The per-test temporary directory.
    :return: The fake, ready to run the wrapper against.
    """
    return FakeRuntime(tmp_path)


def test_wrapper_is_executable():
    """Assert the committed mode lets both callers invoke the wrapper by path."""
    assert os.access(WRAPPER, os.X_OK)


def test_wrapper_passes_stdin_open_to_the_runtime(fake_runtime: FakeRuntime):
    """Assert the runtime keeps stdin open, so the piped-in checker is not empty."""
    result = fake_runtime.run(IMAGE, "restricted")

    assert result.returncode == 0
    assert "-i" in fake_runtime.argv


def test_wrapper_overrides_the_entrypoint_to_python(fake_runtime: FakeRuntime):
    """Assert the image's own interpreter runs instead of its entrypoint."""
    fake_runtime.run(IMAGE, "restricted")

    argv = fake_runtime.argv
    assert "--entrypoint" in argv
    assert argv[argv.index("--entrypoint") + 1] == "python"


def test_wrapper_forwards_the_image_and_mode(fake_runtime: FakeRuntime):
    """Assert the image, the stdin marker and the mode arrive in that order."""
    fake_runtime.run(IMAGE, "unrestricted")

    assert fake_runtime.argv[-3:] == [IMAGE, "-", "unrestricted"]


def test_wrapper_delivers_the_checker_on_stdin(fake_runtime: FakeRuntime):
    """Assert the runtime receives the committed checker verbatim."""
    fake_runtime.run(IMAGE, "restricted")

    assert fake_runtime.stdin == CHECKER.read_text(encoding="utf-8")


def test_wrapper_selects_the_runtime_from_the_environment(tmp_path: Path):
    """Assert an unset ``CONTAINER_RUNTIME`` falls back to ``docker``."""
    fake = FakeRuntime(tmp_path, name="docker")

    result = fake.run(
        IMAGE,
        "restricted",
        environment={"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )

    assert result.returncode == 0
    assert fake.argv[-3:] == [IMAGE, "-", "restricted"]


def test_wrapper_echoes_the_verdict(fake_runtime: FakeRuntime):
    """Assert the checker's verdict reaches the build log."""
    result = fake_runtime.run(IMAGE, "restricted", verdict="verified restricted: 1 (x)")

    assert result.returncode == 0
    assert result.stdout.strip() == "verified restricted: 1 (x)"


def test_wrapper_rejects_an_empty_verdict(fake_runtime: FakeRuntime):
    """Assert a runtime that exits clean without a verdict still fails the gate."""
    result = fake_runtime.run(IMAGE, "restricted", verdict="", exit_code=0)

    assert result.returncode == 1
    assert IMAGE in result.stderr
    assert "never ran" in result.stderr


@pytest.mark.parametrize("exit_code", [1, 7])
def test_wrapper_propagates_a_runtime_failure(
    fake_runtime: FakeRuntime, exit_code: int
):
    """Assert a failing runtime's own status reaches the caller unchanged."""
    result = fake_runtime.run(IMAGE, "restricted", exit_code=exit_code)

    assert result.returncode == exit_code


def test_wrapper_rejects_a_wrong_argument_count(fake_runtime: FakeRuntime):
    """Assert a call missing the mode is refused before any container starts."""
    result = fake_runtime.run(IMAGE)

    assert result.returncode == USAGE_EXIT_CODE
    assert "usage:" in result.stderr
