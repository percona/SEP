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

"""Cover the sep-mysql build's Nomad-witness guard and the compose pin reader."""

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from app import BASE_DIR
from tests.sidecar.conftest import SIDECAR_DIR

CONTAINERFILE = SIDECAR_DIR / "pmm-fb" / "Containerfile.mysql"
COMPOSE = SIDECAR_DIR / "pmm-fb" / "compose.yaml"
PIN_CHECKER = BASE_DIR / "scripts" / "check_pmm_fb_pins.py"
WORKFLOW = BASE_DIR / ".github" / "workflows" / "pmm-fb-nomad-pin.yaml"

GUARD_ANCHOR = "NOMAD_VERSION_FB_TAG"
"""The name whose presence marks the witness guard's ``RUN`` among the others."""

GUARD_ARGS = ("PMM_FB_TAG", "PMM_CLIENT_IMAGE", "NOMAD_VERSION", GUARD_ANCHOR)
"""Names the final stage must declare for either guard to read anything.

``PMM_FB_TAG`` and ``PMM_CLIENT_IMAGE`` are declared before the first ``FROM``,
which Docker scopes to ``FROM`` lines alone. Without a re-declaration inside the
stage both expand to the empty string, the guard's ``[ -z "$PMM_CLIENT_IMAGE" ]``
opens every time, and it passes every build while looking installed.

``NOMAD_VERSION`` is in the list for the same reason and is the worse case: it
is the first clause of *both* guards, so moving its declaration above the first
``FROM``, the natural direction once its three siblings live up there, would
silently retire the original assertion as well as the new one.
"""

RELEASED_CLIENT = "docker.io/percona/pmm-client:3.9.1"
"""A non-empty client image, standing for whatever the arm64 path selects.

The guard tests this slot for emptiness and never for its content, so the value
is arbitrary: this is a stand-in, not a second copy of the pin ``bootstrap.sh``
carries.
"""

ANY_VERSION = "2.0.5"
"""A non-empty ``NOMAD_VERSION``, likewise tested only for emptiness."""

OLD_TAG = "PR-4500-old"
NEW_TAG = "PR-4500-new"

DRIFTED_TAG = "PR-0000-drifted"
"""Tag written into a tampered compose copy, sharing no prefix with a real one."""

WITNESS_DEFAULT = re.compile(r"(?<=NOMAD_VERSION_FB_TAG:-)[^}]*")
SERVER_TAG_DEFAULT = re.compile(r"(?<=pmm-server-fb:\$\{PMM_FB_TAG:-)[^}]*")

CLIENT_REPO = re.compile(r"(?<=FROM \$\{PMM_CLIENT_IMAGE:-)[^:]+")
NOMAD_BINARY = re.compile(r"/\S*/tools/nomad")

VALUELESS_PIN = """\
services:
  pmm-server:
    image: docker.io/perconalab/pmm-server-fb:${PMM_FB_TAG:-T}
  sep-mysql:
    build:
      args:
        PMM_FB_TAG:
        NOMAD_VERSION: ${NOMAD_VERSION:-2.0.5}
        NOMAD_VERSION_FB_TAG: ${NOMAD_VERSION_FB_TAG:-T}
"""
"""A compose file of the right shape whose tag key carries no value.

YAML resolves that to ``None``, which the reader has to reject by name rather
than by letting the regex raise on a non-string.
"""

DECORATED_PIN = """\
services:
  pmm-server:
    image: docker.io/perconalab/pmm-server-fb:${PMM_FB_TAG:-T}
  sep-mysql:
    build:
      args:
        PMM_FB_TAG: prefix-${PMM_FB_TAG:-T}
        NOMAD_VERSION: ${NOMAD_VERSION:-2.0.5}
        NOMAD_VERSION_FB_TAG: ${NOMAD_VERSION_FB_TAG:-T}
"""
"""A slot whose expansion is real but is not the whole value.

Compose builds with ``prefix-T`` while a reader searching for the expansion
anywhere in the string reports ``T``, so the tags appear to agree on a value the
build never uses.
"""


REWIRED_PIN = """\
services:
  pmm-server:
    image: docker.io/perconalab/pmm-server-fb:${PMM_FB_TAG:-T}
  sep-mysql:
    build:
      args:
        PMM_FB_TAG: ${OTHER_TAG:-T}
        NOMAD_VERSION: ${NOMAD_VERSION:-2.0.5}
        NOMAD_VERSION_FB_TAG: ${NOMAD_VERSION_FB_TAG:-T}
"""
"""Every committed default agrees, but one slot reads a different variable.

Exporting ``PMM_FB_TAG`` would then move the server and the witness while this
slot stayed behind: the mismatch the check exists to prevent, reached without
changing a single literal.
"""


def final_stage() -> str:
    """Return the Containerfile's last build stage.

    :return: Everything from the final ``FROM`` line onwards.
    """
    return CONTAINERFILE.read_text(encoding="utf-8").split("\nFROM ")[-1]


def guard_body() -> str:
    """Return the witness guard's shell body, read out of the Containerfile.

    Line continuations are folded so the multi-line ``RUN`` becomes the single
    command ``sh`` would receive. Reading the shipped text is what keeps this
    suite honest: a restated copy of the condition would keep passing after the
    Containerfile's own guard was weakened.

    :return: The guard's command, with the ``RUN`` prefix stripped.
    :raises AssertionError: When no ``RUN`` carries the anchor any more, so a
        reformatted Containerfile fails loudly instead of silently skipping.
    """
    folded = CONTAINERFILE.read_text(encoding="utf-8").replace("\\\n", " ")
    for line in folded.splitlines():
        if line.startswith("RUN ") and GUARD_ANCHOR in line:
            return line.removeprefix("RUN ")
    raise AssertionError(
        f"Containerfile.mysql no longer carries a RUN anchored on {GUARD_ANCHOR}"
    )


def run_guard(
    client: str, version: str, tag: str, witness: str
) -> subprocess.CompletedProcess[str]:
    """Run the extracted guard under ``sh`` with the four build args in the environment.

    :param client: ``PMM_CLIENT_IMAGE``; empty selects the feature-build client.
    :param version: ``NOMAD_VERSION``; empty is the pre-existing opt-out.
    :param tag: ``PMM_FB_TAG`` the build pins.
    :param witness: ``NOMAD_VERSION_FB_TAG``, the tag the version was read from.
    :return: The completed ``sh`` process.
    :raises AssertionError: Propagated from :func:`guard_body` when the
        Containerfile no longer carries the guard.
    """
    return subprocess.run(
        ["sh", "-c", guard_body()],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ["PATH"],
            "PMM_CLIENT_IMAGE": client,
            "NOMAD_VERSION": version,
            "PMM_FB_TAG": tag,
            GUARD_ANCHOR: witness,
        },
    )


def run_checker(*args: str) -> subprocess.CompletedProcess[str]:
    """Run the pin checker, defaulting to the committed compose file.

    :param args: CLI arguments to pass through.
    :return: The completed process.
    """
    return subprocess.run(
        [sys.executable, str(PIN_CHECKER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def drift(pattern: re.Pattern[str], text: str, what: str) -> tuple[str, str]:
    """Rewrite one tag default in ``text`` to :data:`DRIFTED_TAG`.

    :param pattern: A zero-width-prefixed pattern matching just the tag.
    :param text: The compose file's text.
    :param what: What the pattern looks for, for the failure message.
    :return: The tampered text and the tag it replaced.
    :raises AssertionError: When the pattern no longer matches, so a restructured
        compose file fails loudly rather than tampering with nothing.
    """
    match = pattern.search(text)
    assert match is not None, f"compose.yaml no longer carries {what}"
    return f"{text[: match.start()]}{DRIFTED_TAG}{text[match.end() :]}", match.group(0)


@pytest.fixture
def tampered_compose(
    tmp_path: Path,
) -> Callable[[re.Pattern[str], str], tuple[Path, str]]:
    """Return a writer that drops a tampered copy of the compose file in ``tmp_path``.

    :param tmp_path: The per-test temporary directory.
    :return: A callable taking a pattern and a description, returning the copy's
        path and the tag it replaced. It propagates :func:`drift`'s
        ``AssertionError`` when the pattern no longer matches.
    """

    def write(pattern: re.Pattern[str], what: str) -> tuple[Path, str]:
        tampered, original = drift(pattern, COMPOSE.read_text(encoding="utf-8"), what)
        path = tmp_path / "compose.yaml"
        path.write_text(tampered, encoding="utf-8")
        return path, original

    return write


@pytest.mark.parametrize(
    ("pattern", "what"),
    [
        pytest.param(
            CLIENT_REPO, "the feature-build client repository", id="client-repo"
        ),
        pytest.param(NOMAD_BINARY, "the tools/nomad path", id="nomad-path"),
    ],
)
def test_the_gate_reads_the_same_artifact_the_build_copies(
    pattern: re.Pattern[str], what: str
) -> None:
    """Hold the CI job to the image and binary the Containerfile actually names.

    The job spells both out rather than deriving them, so a Containerfile that
    moved either would leave it verifying something the build never copies: a
    green check against the wrong artifact.
    """
    match = pattern.search(CONTAINERFILE.read_text(encoding="utf-8"))
    assert match is not None, f"Containerfile.mysql no longer names {what}"

    assert match.group(0) in WORKFLOW.read_text(encoding="utf-8"), (
        f"{WORKFLOW.name} does not use {what} the Containerfile names"
        f" ({match.group(0)})"
    )


@pytest.mark.parametrize("name", GUARD_ARGS)
def test_final_stage_redeclares_every_arg_the_guard_reads(name: str) -> None:
    """Fail when the stage stops re-declaring an arg, which would mute the guard."""
    assert re.search(rf"^ARG {re.escape(name)}$", final_stage(), re.MULTILINE), (
        f"Containerfile.mysql's final stage no longer declares ARG {name}, so the"
        " witness guard would read it as empty and pass every build"
    )


@pytest.mark.parametrize("name", GUARD_ARGS)
def test_the_extracted_guard_reads_every_arg(name: str) -> None:
    """Fail by name when the shipped guard stops consulting one of its inputs.

    :func:`guard_body` raising is the other half: between them, a Containerfile
    that no longer carries the guard and one that carries a weakened version
    both fail here rather than leaving the truth table exercising nothing.
    """
    assert name in guard_body()


@pytest.mark.parametrize(
    ("client", "version", "tag", "witness", "expected"),
    [
        pytest.param(
            "", ANY_VERSION, NEW_TAG, OLD_TAG, 0, id="feature-build-client-abstains"
        ),
        pytest.param(
            RELEASED_CLIENT, ANY_VERSION, OLD_TAG, OLD_TAG, 0, id="pairing-restated"
        ),
        pytest.param(
            RELEASED_CLIENT, ANY_VERSION, NEW_TAG, OLD_TAG, 1, id="witness-left-behind"
        ),
        pytest.param(RELEASED_CLIENT, "", NEW_TAG, OLD_TAG, 0, id="parity-opted-out"),
        pytest.param(RELEASED_CLIENT, ANY_VERSION, "", OLD_TAG, 1, id="tag-blanked"),
        pytest.param(
            RELEASED_CLIENT, ANY_VERSION, NEW_TAG, "", 1, id="witness-blanked"
        ),
        pytest.param(RELEASED_CLIENT, ANY_VERSION, "", "", 0, id="both-tags-blank"),
    ],
)
def test_guard_verdicts(
    client: str, version: str, tag: str, witness: str, expected: int
) -> None:
    """Check the guard's verdict for each combination of the four build args."""
    assert run_guard(client, version, tag, witness).returncode == expected


def test_the_refusal_names_both_tags() -> None:
    """Point the reader at the two values that disagree, not just at the failure."""
    result = run_guard(RELEASED_CLIENT, ANY_VERSION, NEW_TAG, OLD_TAG)

    assert NEW_TAG in result.stderr
    assert OLD_TAG in result.stderr


def test_committed_pins_agree() -> None:
    """Keep the committed state buildable: every arm64 build reads these defaults."""
    result = run_checker()

    assert result.returncode == 0, result.stdout + result.stderr


def test_a_witness_left_behind_is_caught(
    tampered_compose: Callable[[re.Pattern[str], str], tuple[Path, str]],
) -> None:
    """Reject a compose file whose witness no longer names the pinned feature build."""
    path, original = tampered_compose(WITNESS_DEFAULT, "a NOMAD_VERSION_FB_TAG default")

    result = run_checker(str(path))

    assert result.returncode != 0
    assert original in result.stderr
    assert DRIFTED_TAG in result.stderr


def test_a_drifting_server_tag_is_caught(
    tampered_compose: Callable[[re.Pattern[str], str], tuple[Path, str]],
) -> None:
    """Reject the pre-existing drift the two spellings of the tag always allowed."""
    path, original = tampered_compose(SERVER_TAG_DEFAULT, "a pmm-server-fb image tag")

    result = run_checker(str(path))

    assert result.returncode != 0
    assert original in result.stderr
    assert DRIFTED_TAG in result.stderr


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("services: {}\n", id="no-sep-mysql-service"),
        pytest.param("just a string\n", id="not-a-mapping"),
        pytest.param(VALUELESS_PIN, id="a-pin-with-no-value"),
        pytest.param(REWIRED_PIN, id="a-pin-on-the-wrong-variable"),
        pytest.param(DECORATED_PIN, id="a-pin-with-a-literal-beside-it"),
    ],
)
def test_an_unreadable_compose_file_is_refused(tmp_path: Path, content: str) -> None:
    """Refuse a file this check cannot read, rather than resolving it to nothing.

    A reader that returned empty pins here would compare "" against "", call the
    tags agreed, and report success on a file it never understood.
    """
    path = tmp_path / "compose.yaml"
    path.write_text(content, encoding="utf-8")

    result = run_checker(str(path))

    assert result.returncode != 0
    assert "ERROR" in result.stdout + result.stderr


def test_print_emits_the_committed_witness() -> None:
    """Check that the value the CI gate reads is the one the agreement check validated."""
    match = WITNESS_DEFAULT.search(COMPOSE.read_text(encoding="utf-8"))
    assert match is not None, (
        "compose.yaml no longer carries a NOMAD_VERSION_FB_TAG default"
    )

    result = run_checker("--print", GUARD_ANCHOR)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == match.group(0)
