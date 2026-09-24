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

"""Cover the operator's sentinel-clearing script and its place in the image."""

import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from tests.sidecar.conftest import (
    BUDGET_ASSIGNMENT,
    CONTAINERFILE,
    ENTRYPOINT,
    GATE,
    SCHEMA_STEPS,
    SENTINEL_PREFIX,
    SIDECAR_DIR,
)

CLEAR_SENTINELS = SIDECAR_DIR / "clear_sentinels.sh"

USAGE_EXIT_CODE = 2
"""The exit the script shares with the gate for a malformed invocation."""


def prefixed_copy(source: Path, directory: Path, prefix: str) -> Path:
    """Copy a shipped script with its sentinel prefix moved onto ``prefix``.

    The substitution count is asserted, so a script that grows a second sentinel
    path, or loses its only one, fails the case rather than silently pointing the
    copy at the real ``/tmp`` markers.

    :param source: The shipped script.
    :param directory: Where to write the copy.
    :param prefix: The sentinel prefix the copy should use instead.
    :return: The executable copy.
    """
    text = source.read_text(encoding="utf-8")
    assert text.count(SENTINEL_PREFIX) == 1, (
        f"{source.name} no longer names exactly one sentinel path"
    )
    target = directory / source.name
    target.write_text(text.replace(SENTINEL_PREFIX, prefix), encoding="utf-8")
    target.chmod(0o755)
    return target


def spent_gate(directory: Path, prefix: str) -> Path:
    """Copy the real gate onto ``prefix`` with its budget spent on the first poll.

    A zero budget makes the gate report what is missing and exit without waiting,
    which is what turns it into an observation of the sentinels as they stand.

    :param directory: Where to write the copy.
    :param prefix: The sentinel prefix the copy should read instead.
    :return: The executable copy.
    """
    script = prefixed_copy(GATE, directory, prefix)
    rewritten, count = BUDGET_ASSIGNMENT.subn(
        "readonly WAIT_BUDGET_SECONDS=0", script.read_text(encoding="utf-8")
    )
    assert count == 1, "the gate no longer declares WAIT_BUDGET_SECONDS"
    script.write_text(rewritten, encoding="utf-8")
    return script


def run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a script copy and capture what it reported.

    :param script: The copy to execute.
    :param args: The arguments to pass it.
    :return: The finished process.
    """
    return subprocess.run(
        [str(script), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def sentinel(prefix: str, step: str) -> Path:
    """Return the marker path a schema step publishes under ``prefix``.

    :param prefix: The sentinel prefix in use.
    :param step: The schema step's bare name.
    :return: The marker path.
    """
    return Path(f"{prefix}{step}.ok")


def publish_all(prefix: str) -> None:
    """Write the marker every schema step publishes on a completed run.

    :param prefix: The sentinel prefix in use.
    """
    for step in SCHEMA_STEPS:
        sentinel(prefix, step).touch()


@pytest.fixture
def sentinel_prefix() -> Iterator[str]:
    """Return a sentinel prefix unique to this case, removing its markers afterwards.

    The script accepts only real step names, so unlike the gate's suite this one
    cannot isolate itself with unique names; a unique prefix keeps it off a
    developer's real sentinels and off a sibling xdist worker's.

    :return: A prefix standing in for ``/tmp/migrate-``.
    """
    prefix = f"{SENTINEL_PREFIX}{uuid4().hex}-"
    yield prefix
    for step in SCHEMA_STEPS:
        path = sentinel(prefix, step)
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink(missing_ok=True)


@pytest.fixture
def script(tmp_path: Path, sentinel_prefix: str) -> Path:
    """Return the script copy this case runs, pointed at its own markers.

    :param tmp_path: The per-test temporary directory.
    :param sentinel_prefix: The prefix standing in for ``/tmp/migrate-``.
    :return: The executable copy.
    """
    return prefixed_copy(CLEAR_SENTINELS, tmp_path, sentinel_prefix)


def test_the_script_knows_every_schema_step():
    """Pin the script's literal list to the program table it must agree with.

    The list is declared literally, as ``healthcheck.sh`` declares its own, so
    this pin is what keeps a fifth one-shot from being added to the program table
    without the operator's clearing command learning about it.
    """
    assert f"readonly SCHEMA_STEPS=({' '.join(SCHEMA_STEPS)})" in (
        CLEAR_SENTINELS.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize(
    "named",
    [("inventory",), ("extensions", "tasks"), SCHEMA_STEPS],
    ids=["one", "some", "all"],
)
def test_a_named_step_loses_only_its_own_sentinel(
    script: Path, sentinel_prefix: str, named: tuple[str, ...]
):
    """Remove exactly the named steps' markers and report what was removed.

    An operator re-runs a subset, so clearing more than was asked would hold the
    APIs on steps that are not being re-run at all.
    """
    publish_all(sentinel_prefix)

    result = run(script, *named)

    assert result.returncode == 0, result.stderr
    assert not any(sentinel(sentinel_prefix, step).exists() for step in named)
    assert all(
        sentinel(sentinel_prefix, step).exists()
        for step in SCHEMA_STEPS
        if step not in named
    )
    assert f"cleared: {' '.join(named)}" in result.stdout


@pytest.mark.parametrize(
    "unknown",
    ["nosuchstep", "migrate-extensions", "sep inventory", "", "../extensions"],
    ids=["unknown", "program-name", "two-words", "empty", "path"],
)
def test_an_unknown_step_is_refused_before_anything_is_removed(
    script: Path, sentinel_prefix: str, unknown: str
):
    """Refuse the whole invocation on a bad name, having removed nothing.

    A partial clear is the worse outcome: the operator sees a failure and
    restarts nothing, while the steps already cleared leave the container
    reporting unhealthy with no re-run coming to republish their markers.
    Validating every name first makes a typo free to retry.

    ``migrate-extensions`` is the natural mistake, since ``supervisorctl`` takes program
    names, and ``sep inventory`` is what a substring membership test would
    wrongly accept; ``""`` and ``../extensions`` are refused before any path is built
    from them.
    """
    publish_all(sentinel_prefix)

    result = run(script, "extensions", unknown)

    assert result.returncode == USAGE_EXIT_CODE
    assert all(sentinel(sentinel_prefix, step).exists() for step in SCHEMA_STEPS)
    assert f"unknown schema step '{unknown}'" in result.stderr
    assert f"expected one of: {' '.join(SCHEMA_STEPS)}" in result.stderr


def test_no_step_is_a_usage_error(script: Path):
    """Refuse an empty argument list rather than succeeding vacuously.

    Mirrors the gate, whose own empty-list refusal keeps a silent no-op from
    reading as a completed clear.
    """
    result = run(script)

    assert result.returncode == USAGE_EXIT_CODE
    assert result.stderr.startswith("usage:")


def test_clearing_an_absent_sentinel_succeeds(script: Path, sentinel_prefix: str):
    """Accept a step whose marker was never published, so a re-clear is safe.

    An operator who clears twice, or who clears a step that failed its last run,
    is in exactly the state the clear is meant to produce.
    """
    assert not any(sentinel(sentinel_prefix, step).exists() for step in SCHEMA_STEPS)

    result = run(script, "extensions")

    assert result.returncode == 0, result.stderr


def test_a_repeated_step_is_accepted(script: Path, sentinel_prefix: str):
    """Accept the same step twice, since the second removal has nothing left to do."""
    publish_all(sentinel_prefix)

    result = run(script, "extensions", "extensions")

    assert result.returncode == 0, result.stderr
    assert not sentinel(sentinel_prefix, "extensions").exists()
    assert all(
        sentinel(sentinel_prefix, step).exists()
        for step in SCHEMA_STEPS
        if step != "extensions"
    )


def test_a_stale_sentinel_releases_a_gate_when_nothing_was_cleared(
    tmp_path: Path, sentinel_prefix: str
):
    """Establish the premise: a previous run's markers release a restarted gate.

    This is the control for the case below. Without it, that case proves only
    that a gate blocks on a missing marker, not that the marker would otherwise
    have been there to release it.
    """
    publish_all(sentinel_prefix)

    result = run(spent_gate(tmp_path, sentinel_prefix), *SCHEMA_STEPS)

    assert result.returncode == 0, result.stderr


def test_a_cleared_step_holds_a_restarted_gate(
    script: Path, tmp_path: Path, sentinel_prefix: str
):
    """Hold a gate on exactly the step that was cleared, and on no other.

    Once the script has returned, a gate started afterwards cannot observe the
    cleared marker, which is what makes the documented sequence (clear, then
    restart) safe whatever order supervisorctl starts the programs in.
    """
    publish_all(sentinel_prefix)

    assert run(script, "extensions").returncode == 0

    result = run(spent_gate(tmp_path, sentinel_prefix), *SCHEMA_STEPS)
    _, _, waiting_for = result.stderr.partition("waiting for: ")

    assert result.returncode != 0
    assert waiting_for.split() == ["extensions"]


def test_a_marker_that_cannot_be_removed_fails_the_run(
    script: Path, sentinel_prefix: str
):
    """Stop at a marker that will not go, leaving later steps uncleared and unreported.

    ``errexit`` makes the failure the operator's signal to stop: the steps named
    after the failing one may still hold a marker, so the README's "continue only
    if it exits 0" is a real gate rather than a caution.
    """
    publish_all(sentinel_prefix)
    sentinel(sentinel_prefix, "extensions").unlink()
    sentinel(sentinel_prefix, "extensions").mkdir()

    result = run(script, "inventory", "extensions", "tasks")

    assert result.returncode not in (0, USAGE_EXIT_CODE)
    assert not sentinel(sentinel_prefix, "inventory").exists()
    assert sentinel(sentinel_prefix, "tasks").exists()
    assert "cleared:" not in result.stdout


def test_the_script_reaches_the_image():
    """Assert the script is copied in; bundle.tgz carries no sidecar/ file."""
    assert (
        f"./sidecar/{CLEAR_SENTINELS.name} ./{CLEAR_SENTINELS.name}"
        in CONTAINERFILE.read_text(encoding="utf-8")
    )


def test_the_script_is_executable_in_the_image():
    """Require the executable mode: an operator runs it directly, not via sh."""
    copy_lines = [
        line
        for line in CONTAINERFILE.read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY") and CLEAR_SENTINELS.name in line
    ]

    assert len(copy_lines) == 1
    assert "--chmod=550" in copy_lines[0]


def test_the_entrypoint_points_supervisorctl_reruns_at_the_script():
    """Keep PID 1's comment naming the script that covers the path it does not.

    The entrypoint's clearing is the container-start half of the same job, and
    its comment is where a reader looking at the automatic clearing learns the
    supervisorctl path has its own. A rename that left the comment behind fails
    here rather than stranding that reader.
    """
    assert CLEAR_SENTINELS.name in ENTRYPOINT.read_text(encoding="utf-8")
