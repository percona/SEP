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

"""Run the MongoDB detection scripts against a host with and without ``mongod``.

Three builtin scripts locate a MongoDB artefact by walking a chain: the running
process command line, then the config file, then well-known paths. Two of them
exist for the case where the process is *not* running, so the chain must reach
its fallbacks and, when every step fails, end with a message naming what it could
not find and which option supplies it. These tests drive the real scripts under
``bash`` with ``pgrep`` and ``ps`` replaced by stubs on ``PATH``, so both the
absent and the running process can be staged without touching the host.

The scripts need GNU ``getopt`` and GNU ``date``, so the module is skipped on a
BSD userland and runs in the Linux CI matrix. The well-known locations are absolute
paths under ``/etc`` and ``/var`` that a test cannot create, so the config-file step
is driven through a copy of the script whose first candidate names a staged file —
see :func:`run_snippet_with_staged_config`. The well-known *data* directories are
covered only by the not-found branch, which stands down on a host that has one.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.extensions.snippets.config import snippets_settings

FAKE_MONGOD_PID = "4242"
# GNU getopt answers `--test` with status 4; the BSD one prints `--` and exits 0.
GNU_GETOPT_TEST_STATUS = 4
DEFAULT_MONGODB_LOG = Path("/var/log/mongodb/mongod.log")
FIRST_WELL_KNOWN_CONFIG = "/etc/mongod.conf"
FIRST_WELL_KNOWN_CONFIG_RE = re.compile(
    rf"(?<=[\"'\s]){re.escape(FIRST_WELL_KNOWN_CONFIG)}(?![\w./])"
)
WELL_KNOWN_CONFIG_PATHS = (
    Path(FIRST_WELL_KNOWN_CONFIG),
    Path("/etc/mongodb.conf"),
    Path("/usr/local/etc/mongod.conf"),
    Path("/opt/homebrew/etc/mongod.conf"),
    Path("/etc/mongos.conf"),
)
WELL_KNOWN_DATA_DIRS = (
    Path("/var/lib/mongodb"),
    Path("/data/db"),
    Path("/var/lib/mongo"),
)


def _host_configs() -> tuple[Path, ...]:
    """Return the well-known config files this host actually has.

    The scripts read a config before falling back to well-known paths, so a host
    carrying one can resolve a log or data directory the test never staged. Every
    test that asserts on the nothing-found branch has to stand down on such a host.

    :return: The existing paths, empty when the host carries none.
    """
    return tuple(path for path in WELL_KNOWN_CONFIG_PATHS if path.exists())


def _has_gnu_userland() -> bool:
    """Return whether the tools the scripts need are the GNU ones they were written for.

    :return: ``True`` when ``bash``, GNU ``getopt`` and GNU ``date`` are on ``PATH``.
    """
    if any(shutil.which(tool) is None for tool in ("bash", "getopt", "date", "ps")):
        return False
    try:
        getopt = subprocess.run(["getopt", "--test"], capture_output=True, check=False)
        date = subprocess.run(
            ["date", "-d", "now", "+%s"], capture_output=True, check=False
        )
    except OSError:
        return False
    return getopt.returncode == GNU_GETOPT_TEST_STATUS and date.returncode == 0


pytestmark = pytest.mark.skipif(
    not _has_gnu_userland(), reason="requires bash with GNU getopt and date"
)


@dataclass
class ProcessStubs:
    """Stage ``pgrep`` and ``ps`` answers for the scripts under test.

    :param bin_dir: The directory prepended to ``PATH`` for the run.
    """

    bin_dir: Path

    def _write(self, name: str, body: str) -> None:
        """Stage one executable stub in the directory that fronts ``PATH``.

        :param name: The command the stub answers for.
        :param body: The shell body to run, appended to a ``bash`` shebang.
        """
        path = self.bin_dir / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def no_mongod(self) -> None:
        """Make ``pgrep`` report that no process matches."""
        self._write("pgrep", "exit 1")

    def running_mongod(self, command_line: str) -> None:
        """Make ``pgrep`` find one ``mongod`` and ``ps`` describe it with ``command_line``.

        Any other ``ps`` invocation is handed to the real binary so the scripts'
        unrelated process listings keep working.

        :param command_line: The ``args=`` line ``ps`` reports for the fake process.
        """
        real_ps = shutil.which("ps")
        self._write("pgrep", f"echo {FAKE_MONGOD_PID}")
        self._write(
            "ps",
            f'if [[ "$*" == *"-p {FAKE_MONGOD_PID}"* ]]; then\n'
            f'    if [[ "$*" == *"comm="* ]]; then echo mongod; else echo "{command_line}"; fi\n'
            f"    exit 0\n"
            f"fi\n"
            f'exec "{real_ps}" "$@"',
        )

    def environment(self) -> dict[str, str]:
        """Return the environment that puts the stubs first on ``PATH``.

        :return: A copy of the current environment with ``PATH`` and locale adjusted.
        """
        return {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ['PATH']}",
            "LC_ALL": "C",
        }


@pytest.fixture
def stubs(tmp_path: Path) -> ProcessStubs:
    """Provide process stubs staged in a fresh directory.

    :param tmp_path: The per-test temporary directory holding the stub ``bin``.
    :return: The stubs, with no command staged yet.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    return ProcessStubs(bin_dir)


def _run_bash(
    script: Path, args: tuple[str, ...], env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run a script under ``bash`` and capture both streams.

    :param script: The script to run.
    :param args: The command-line arguments for the script.
    :param env: The environment for the run.
    :param cwd: The working directory, so a script writing files lands in a temp dir.
    :return: The completed process.
    """
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=60,
        check=False,
    )


def run_snippet(
    name: str, *args: str, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run a builtin script as it ships.

    :param name: The script filename under the snippets directory.
    :param args: The command-line arguments for the script.
    :param env: The environment for the run.
    :param cwd: The working directory for the run.
    :return: The completed process.
    """
    return _run_bash(snippets_settings.SNIPPETS_DIR / name, args, env, cwd)


def run_snippet_with_staged_config(
    name: str, *args: str, conf: Path, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Run a builtin script with its first well-known config path pointed at ``conf``.

    The config-file step of the detection chain reads absolute paths under ``/etc``
    that a test cannot create, so exercising that step means running a copy whose
    first candidate names a staged file instead. Only whole-path occurrences of that
    candidate are rewritten, so the longer candidates ending in the same characters —
    ``/usr/local/etc/mongod.conf`` and ``/opt/homebrew/etc/mongod.conf`` — keep
    pointing where they did. A substitution is asserted, so a script that stops
    consulting the well-known location fails this test rather than silently covering
    nothing.

    :param name: The script filename under the snippets directory.
    :param args: The command-line arguments for the script.
    :param conf: The config file the copy should find.
    :param env: The environment for the run.
    :param cwd: The working directory for the run, which also holds the copy.
    :return: The completed process.
    """
    source = (snippets_settings.SNIPPETS_DIR / name).read_text(encoding="utf-8")
    staged, substitutions = FIRST_WELL_KNOWN_CONFIG_RE.subn(str(conf), source)
    assert substitutions, f"{name} no longer reads {FIRST_WELL_KNOWN_CONFIG}"
    copy = cwd / f"staged-{name}"
    copy.write_text(staged, encoding="utf-8")
    return _run_bash(copy, args, env, cwd)


class TestMongodbConfigFiles:
    """Exercise the config discovery script, whose only path is detection."""

    def test_no_mongod_walks_the_whole_chain(self, stubs, tmp_path):
        """Reach the footer instead of dying at the process step."""
        stubs.no_mongod()
        result = run_snippet(
            "mongodb_config_files.sh", env=stubs.environment(), cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert "Checking running mongod/mongos process" in result.stdout
        assert "=== Done ===" in result.stdout

    @pytest.mark.skipif(
        any(_host_configs()),
        reason="host has a MongoDB config file at a well-known path",
    )
    def test_no_config_anywhere_names_what_was_not_found(self, stubs, tmp_path):
        """Say the config was not found; the script takes no option to name instead."""
        stubs.no_mongod()
        result = run_snippet(
            "mongodb_config_files.sh", env=stubs.environment(), cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert "No MongoDB configuration file found" in result.stdout

    def test_no_mongod_still_reads_a_well_known_config(self, stubs, tmp_path):
        """Print the config the well-known step finds once the process step found none."""
        conf = tmp_path / "mongod.conf"
        conf.write_text("storage:\n  dbPath: /tmp/data\n", encoding="utf-8")
        stubs.no_mongod()
        result = run_snippet_with_staged_config(
            "mongodb_config_files.sh", conf=conf, env=stubs.environment(), cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert f"---- Found: {conf} ----" in result.stdout
        assert "dbPath: /tmp/data" in result.stdout
        assert "No MongoDB configuration file found" not in result.stdout

    @pytest.mark.parametrize(
        "flag", ["--config {conf}", "-f {conf}", "--config={conf}"]
    )
    def test_running_mongod_resolves_the_config_from_the_process(
        self, stubs, tmp_path, flag
    ):
        """Read the config path off the process command line in each spelling mongod accepts."""
        conf = tmp_path / "mongod.conf"
        conf.write_text("storage:\n  dbPath: /tmp/data\n", encoding="utf-8")
        stubs.running_mongod(f"mongod {flag.format(conf=conf)}")
        result = run_snippet(
            "mongodb_config_files.sh", env=stubs.environment(), cwd=tmp_path
        )

        assert result.returncode == 0, result.stderr
        assert (
            f"Detected config file from running mongod process: {conf}" in result.stdout
        )
        assert f"---- Found: {conf} ----" in result.stdout
        assert "dbPath: /tmp/data" in result.stdout


class TestMongodbLogExtractor:
    """Exercise the log extractor resolving its log path: process, then config."""

    TIME_ARGS = (
        "--time",
        "2023-10-27T15:30:00",
        "--minutes",
        "3",
        "--output",
        "stdout",
    )

    @staticmethod
    def _write_log(path: Path) -> None:
        """Write a log holding one line inside the extraction window and one outside it.

        :param path: The log file to create.
        """
        path.write_text(
            "2023-10-27T15:29:00.000+00:00 I CONTROL inside the window\n"
            "2023-10-27T15:40:00.000+00:00 I CONTROL outside the window\n",
            encoding="utf-8",
        )

    @pytest.mark.skipif(
        DEFAULT_MONGODB_LOG.exists() or any(_host_configs()),
        reason="host has a MongoDB config file or a log at the default path",
    )
    def test_no_mongod_and_no_config_names_the_option_to_pass(self, stubs, tmp_path):
        """Fail with a message naming the missing log and the option, not with silence."""
        stubs.no_mongod()
        result = run_snippet(
            "mongodb_log_extractor.sh",
            *self.TIME_ARGS,
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 1
        assert result.stderr.strip(), "the script exited without saying why"
        assert "MongoDB log file not found" in result.stderr
        assert "--log-file" in result.stderr

    def test_no_mongod_falls_through_to_the_config_step(self, stubs, tmp_path):
        """Resolve the log from the well-known config once the process step found none."""
        log = tmp_path / "mongod.log"
        self._write_log(log)
        conf = tmp_path / "mongod.conf"
        conf.write_text(
            f"systemLog:\n  destination: file\n  path: {log}\n", encoding="utf-8"
        )
        stubs.no_mongod()
        result = run_snippet_with_staged_config(
            "mongodb_log_extractor.sh",
            *self.TIME_ARGS,
            conf=conf,
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert f"Detected log file from config ({conf}): {log}" in result.stderr
        assert "inside the window" in result.stdout
        assert "outside the window" not in result.stdout

    def test_running_mongod_resolves_the_log_through_its_config(self, stubs, tmp_path):
        """Follow the process command line to the config and the config to the log."""
        log = tmp_path / "mongod.log"
        self._write_log(log)
        conf = tmp_path / "mongod.conf"
        conf.write_text(
            f"systemLog:\n  destination: file\n  path: {log}\n", encoding="utf-8"
        )
        stubs.running_mongod(f"mongod --config {conf}")
        result = run_snippet(
            "mongodb_log_extractor.sh",
            *self.TIME_ARGS,
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert f"Detected log file from config ({conf}): {log}" in result.stderr
        assert "inside the window" in result.stdout
        assert "outside the window" not in result.stdout

    def test_explicit_log_file_skips_detection(self, stubs, tmp_path):
        """Use the given log without consulting the process at all."""
        log = tmp_path / "mongod.log"
        self._write_log(log)
        stubs.no_mongod()
        result = run_snippet(
            "mongodb_log_extractor.sh",
            *self.TIME_ARGS,
            "--log-file",
            str(log),
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert "inside the window" in result.stdout
        assert "Detected log file" not in result.stderr


class TestMongodbFtdcCollect:
    """Exercise the FTDC collector resolving its data directory: process, then config."""

    @staticmethod
    def _stage_data_dir(root: Path) -> Path:
        """Build a data directory holding one FTDC metrics file.

        :param root: The directory to create the data directory under.
        :return: The data directory, with its ``diagnostic.data`` populated.
        """
        data_dir = root / "data"
        (data_dir / "diagnostic.data").mkdir(parents=True)
        (
            data_dir / "diagnostic.data" / "metrics.2023-10-27T15-00-00Z-00000"
        ).write_bytes(b"\x00" * 16)
        return data_dir

    @pytest.mark.skipif(
        any(path.exists() for path in WELL_KNOWN_DATA_DIRS) or any(_host_configs()),
        reason="host has a MongoDB config file or a data directory",
    )
    def test_no_mongod_and_no_data_dir_names_the_option_to_pass(self, stubs, tmp_path):
        """Fail with a message naming the missing directory and the option, not just the banner."""
        stubs.no_mongod()
        result = run_snippet(
            "mongodb_ftdc_collect.sh",
            "--dest",
            str(tmp_path / "dest"),
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 1
        assert "Could not locate the MongoDB data directory" in result.stdout
        assert "--data-dir" in result.stdout

    def test_no_mongod_falls_through_to_the_config_step(self, stubs, tmp_path):
        """Resolve the data directory from the well-known config, then collect from it."""
        data_dir = self._stage_data_dir(tmp_path)
        conf = tmp_path / "mongod.conf"
        conf.write_text(f"storage:\n  dbPath: {data_dir}\n", encoding="utf-8")
        stubs.no_mongod()
        result = run_snippet_with_staged_config(
            "mongodb_ftdc_collect.sh",
            "--dest",
            str(tmp_path / "dest"),
            conf=conf,
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert (
            f"Detected data directory from config ({conf}): {data_dir}" in result.stdout
        )
        assert "Copied 1 file(s)" in result.stdout

    @pytest.mark.parametrize("flag", ["--dbpath {data_dir}", "--dbpath={data_dir}"])
    def test_running_mongod_resolves_the_data_dir_from_the_process(
        self, stubs, tmp_path, flag
    ):
        """Read the data directory off the process command line in each spelling mongod accepts."""
        data_dir = self._stage_data_dir(tmp_path)
        stubs.running_mongod(f"mongod {flag.format(data_dir=data_dir)}")
        result = run_snippet(
            "mongodb_ftdc_collect.sh",
            "--dest",
            str(tmp_path / "dest"),
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert (
            f"Detected data directory from running process: {data_dir}" in result.stdout
        )
        assert "Total: 1 file(s)" in result.stdout
        assert "Copied 1 file(s)" in result.stdout

    def test_explicit_data_dir_lists_and_copies(self, stubs, tmp_path):
        """Use the given directory without consulting the process at all."""
        data_dir = self._stage_data_dir(tmp_path)
        stubs.no_mongod()
        dest = tmp_path / "dest"
        result = run_snippet(
            "mongodb_ftdc_collect.sh",
            "--data-dir",
            str(data_dir),
            "--dest",
            str(dest),
            env=stubs.environment(),
            cwd=tmp_path,
        )

        assert result.returncode == 0, result.stderr
        assert "Total: 1 file(s)" in result.stdout
        assert (dest / "metrics.2023-10-27T15-00-00Z-00000").exists()

    @pytest.mark.skipif(
        os.geteuid() == 0, reason="root reads a directory regardless of its mode"
    )
    def test_unreadable_ftdc_dir_does_not_abort_silently(self, stubs, tmp_path):
        """Report the directory as empty rather than dying on the failed listing."""
        data_dir = self._stage_data_dir(tmp_path)
        ftdc_dir = data_dir / "diagnostic.data"
        ftdc_dir.chmod(0o000)
        stubs.no_mongod()
        try:
            result = run_snippet(
                "mongodb_ftdc_collect.sh",
                "--data-dir",
                str(data_dir),
                "--dest",
                "",
                env=stubs.environment(),
                cwd=tmp_path,
            )
        finally:
            ftdc_dir.chmod(0o755)

        assert result.returncode == 0, result.stderr
        assert f"=== FTDC directory: {ftdc_dir} ===" in result.stdout
        assert f"No FTDC files found in '{ftdc_dir}'." in result.stdout
