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
"""Cover the side-car's encryption-key resolution, freshness guard and mint."""

import asyncio
import base64
import fcntl
import os
import socket
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, insert

from app import BASE_DIR
from app.core.encryption import is_encrypted
from app.core.settings_override.models import SettingOverride
from sidecar import encryption_key as helper
from tests.sidecar.conftest import SIDECAR_DIR

HELPER_SCRIPT = SIDECAR_DIR / "encryption_key.py"

SERVICE_PREFIXES = ("SEP", "INVENTORY", "TASKS")
"""The three services whose databases the freshness probe has to clear."""

DATABASE_FILENAMES = {
    "SEP": "sep.db",
    "INVENTORY": "inventory.db",
    "TASKS": "tasks.db",
}
"""One distinct SQLite file per service, so a single-DSN probe fails these tests."""

KEY_FILE_MODE = 0o600

UNREACHABLE_PORT = 1
"""A privileged port nothing in the test environment listens on."""

SHORT_PROBE_TIMEOUT = "1.5"
"""Short enough that an unreachable database is refused inside a test's patience."""

BLOCKED_RUN_SECONDS = 6.0
"""Long enough to clear interpreter start, so a timeout means the lock held."""

RETRIED_PROBE_TIMEOUT = 2.0
"""A bound long enough that reaching it can only mean the probe retried.

A refused connection returns instantly, so a run that spends this long before
giving up cannot have refused on the first error.
"""

RESTORE_HINT = "sep-state"
"""What a refusal has to name so an operator can act on it."""


def fernet_key() -> str:
    """Return a freshly generated Fernet key.

    :return: A key the settings validator accepts.
    """
    return Fernet.generate_key().decode("ascii")


def ciphertext(plaintext: str = "a-stored-credential") -> str:
    """Return a real Fernet token, built under a key this process discards.

    Built with :class:`~cryptography.fernet.Fernet` rather than written as a
    literal so the fixtures stay valid tokens if the format ever moves, and
    under a throwaway key because the probe must recognise ciphertext it
    cannot decrypt.

    :param plaintext: The value to encrypt.
    :return: The token, as it would sit in a stored override.
    """
    return Fernet(fernet_key().encode()).encrypt(plaintext.encode()).decode("ascii")


def create_database(directory: Path, filename: str, *values: Any) -> None:
    """Create one service's ``settingoverride`` table and seed it.

    :param directory: The directory to place the SQLite file in.
    :param filename: The database file's name.
    :param values: One stored override value per row, JSON-storable.
    """
    engine = create_engine(f"sqlite:///{directory / filename}")
    SettingOverride.__table__.create(engine)
    if values:
        with engine.begin() as connection:
            connection.execute(
                insert(SettingOverride.__table__),
                [
                    {
                        "setting_class": "SEP_SETTINGS",
                        "key": f"KEY_{index}",
                        "value": value,
                        "is_active": True,
                    }
                    for index, value in enumerate(values)
                ],
            )
    engine.dispose()


def database_environment(directory: Path) -> dict[str, str]:
    """Return the environment pointing each service at its own SQLite file.

    :param directory: The directory holding the three database files.
    :return: One ``NAME`` variable per service.
    """
    return {
        f"{prefix}__DATABASE__NAME": str(directory / DATABASE_FILENAMES[prefix])
        for prefix in SERVICE_PREFIXES
    }


def unreachable_environment(
    prefix: str, port: int = UNREACHABLE_PORT
) -> dict[str, str]:
    """Return the environment pointing one service at a database nothing answers.

    :param prefix: The service whose endpoint to break.
    :param port: The port to aim it at.
    :return: The PostgreSQL connection variables for that service alone.
    """
    return {
        f"{prefix}__DATABASE__ENGINE": "postgresql+asyncpg",
        f"{prefix}__DATABASE__HOST": "127.0.0.1",
        f"{prefix}__DATABASE__PORT": str(port),
        f"{prefix}__DATABASE__USER": "sep",
        f"{prefix}__DATABASE__NAME": "sep",
    }


@pytest.fixture
def stalled_database_port() -> Iterator[int]:
    """Return a port that completes the TCP handshake and then answers nothing.

    A refused connection fails immediately and never reaches the timeout, so
    this is what exercises the bound rather than the error path beside it: the
    kernel accepts into the backlog while nothing ever reads, leaving the
    driver waiting on a startup reply that does not come.

    :return: The listening port.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        yield listener.getsockname()[1]


def run_helper(
    directory: Path, *, timeout: float | None = None, **environment: str
) -> subprocess.CompletedProcess[str]:
    """Run the helper as ``entrypoint.sh`` runs it, from a minimal environment.

    ``ENCRYPTION_KEY`` is deliberately absent from the base: the whole point of
    the helper is what it does when nothing supplied one.

    :param directory: The working directory, which is also where the databases
        and the state directory live.
    :param timeout: How long to wait before raising
        :class:`subprocess.TimeoutExpired`, or ``None`` to wait indefinitely.
    :param environment: Variables to add over the base.
    :return: The completed run, whose stdout carries the resolved key.
    """
    base = {
        "PATH": os.environ["PATH"],
        "PYTHONPATH": str(BASE_DIR),
        "SEP_STATE_DIR": str(directory / "state"),
        "SEP_ENCRYPTION_PROBE_TIMEOUT": SHORT_PROBE_TIMEOUT,
        **database_environment(directory),
    }
    return subprocess.run(
        [sys.executable, str(HELPER_SCRIPT)],
        cwd=str(directory),
        env={**base, **environment},
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


@pytest.fixture
def fresh_deployment(tmp_path: Path) -> Path:
    """Create three empty service databases and return their directory.

    :param tmp_path: The per-test temporary directory.
    :return: The directory holding the three files.
    """
    for filename in DATABASE_FILENAMES.values():
        create_database(tmp_path, filename)
    return tmp_path


def persisted_key_path(directory: Path) -> Path:
    """Return where the helper persists a minted key under ``directory``.

    :param directory: The working directory passed to :func:`run_helper`.
    :return: The persisted key's path.
    """
    return directory / "state" / helper.PERSISTED_FILENAME


def test_a_fresh_deployment_mints_a_key_and_persists_it(fresh_deployment: Path):
    """Mint on a deployment with no ciphertext, which is the out-of-box path."""
    result = run_helper(fresh_deployment)

    assert result.returncode == 0, result.stderr
    minted = result.stdout.strip()
    assert minted
    assert persisted_key_path(fresh_deployment).read_text(encoding="utf-8") == minted


def test_a_minted_key_is_one_the_settings_validator_accepts(fresh_deployment: Path):
    """Mint a real Fernet key, which is what every supervised program then builds."""
    result = run_helper(fresh_deployment)

    assert result.returncode == 0, result.stderr
    cipher = Fernet(result.stdout.strip().encode())
    assert cipher.decrypt(cipher.encrypt(b"an-override-value")) == b"an-override-value"


def test_a_minted_key_is_persisted_owner_only(fresh_deployment: Path):
    """Keep the key off every other account in the container's namespace."""
    run_helper(fresh_deployment)

    mode = persisted_key_path(fresh_deployment).stat().st_mode
    assert stat.S_IMODE(mode) == KEY_FILE_MODE


def test_an_explicit_key_is_returned_without_minting(fresh_deployment: Path):
    """Return channel 1 untouched, which no lower channel may ever displace."""
    supplied = fernet_key()

    result = run_helper(fresh_deployment, ENCRYPTION_KEY=supplied)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == supplied
    assert not persisted_key_path(fresh_deployment).exists()


def test_a_mounted_key_file_is_returned_without_minting(fresh_deployment: Path):
    """Resolve channel 2, so a helper run standalone agrees with the shell."""
    mounted = fernet_key()
    secrets_dir = fresh_deployment / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "ENCRYPTION_KEY").write_text(mounted, encoding="utf-8")

    result = run_helper(fresh_deployment, SECRETS_DIR=str(secrets_dir))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == mounted
    assert not persisted_key_path(fresh_deployment).exists()


def test_a_persisted_key_is_returned_byte_for_byte(fresh_deployment: Path):
    """Return the same key an earlier start minted, which the rows were written under."""
    first = run_helper(fresh_deployment)

    second = run_helper(fresh_deployment)

    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == first.stdout.strip()


@pytest.mark.parametrize("prefix", SERVICE_PREFIXES)
def test_a_persisted_key_resolves_without_reaching_any_database(
    fresh_deployment: Path, prefix: str
):
    """Skip the probe entirely on a restart, which owes no database dependency.

    Every service is pointed at an endpoint nothing answers, so a run that
    probed could only refuse. Exiting 0 with the persisted key is therefore
    the observable proof the mint path was never entered.
    """
    first = run_helper(fresh_deployment)

    second = run_helper(fresh_deployment, **unreachable_environment(prefix))

    assert second.returncode == 0, second.stderr
    assert second.stdout.strip() == first.stdout.strip()


def test_a_scalar_ciphertext_row_refuses_the_mint(tmp_path: Path):
    """Refuse where a plain string column already holds a token."""
    create_database(tmp_path, DATABASE_FILENAMES["SEP"], ciphertext())
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert result.returncode != 0
    assert not result.stdout.strip()
    assert RESTORE_HINT in result.stderr


def test_a_ciphertext_leaf_nested_in_a_list_refuses_the_mint(tmp_path: Path):
    """Refuse on the ``PROVIDERS`` shape, which a top-level check cannot see.

    Captured from a real row: ``jsonb_typeof`` is ``array`` and the token is
    the ``ROUTING_KEY`` leaf, so ``is_encrypted`` applied to the row's own
    value finds nothing at all.
    """
    providers = [{"PROVIDER": "pagerduty", "ROUTING_KEY": ciphertext()}]
    create_database(tmp_path, DATABASE_FILENAMES["SEP"], providers)
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert result.returncode != 0
    assert not result.stdout.strip()


def test_a_ciphertext_leaf_nested_in_a_mapping_refuses_the_mint(tmp_path: Path):
    """Refuse on the ``DIAGNOSTICS_DELIVERY_INPUTS`` shape, nested a level deeper."""
    inputs = {"primary": {"endpoint": "https://example.test", "api_key": ciphertext()}}
    create_database(tmp_path, DATABASE_FILENAMES["SEP"], inputs)
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert result.returncode != 0
    assert not result.stdout.strip()


@pytest.mark.parametrize("prefix", SERVICE_PREFIXES)
def test_ciphertext_in_any_single_service_refuses_the_mint(tmp_path: Path, prefix: str):
    """Scan all three databases, whose rows are never read cross-service."""
    for name, filename in DATABASE_FILENAMES.items():
        rows = (ciphertext(),) if name == prefix else ()
        create_database(tmp_path, filename, *rows)

    result = run_helper(tmp_path)

    assert result.returncode != 0
    assert not result.stdout.strip()


def test_a_plaintext_only_deployment_still_mints(tmp_path: Path):
    """Mint where overrides exist but none of them is encrypted.

    Refusing on any non-scalar row would block the mint on deployments whose
    only nested overrides carry no secret at all, so the guard has to read the
    leaves rather than the row's shape.
    """
    create_database(
        tmp_path,
        DATABASE_FILENAMES["SEP"],
        "a-plain-value",
        [{"PROVIDER": "pagerduty", "SEVERITY": "critical"}],
        {"primary": {"endpoint": "https://example.test"}},
    )
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_an_absent_override_table_counts_as_fresh(tmp_path: Path):
    """Mint against a database whose schema has never been applied."""
    engine = create_engine(f"sqlite:///{tmp_path / DATABASE_FILENAMES['SEP']}")
    engine.connect().close()
    engine.dispose()
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


@pytest.mark.parametrize("prefix", SERVICE_PREFIXES)
def test_an_unreachable_database_refuses_the_mint(fresh_deployment: Path, prefix: str):
    """Refuse where freshness cannot be proven, for any one of the three."""
    result = run_helper(fresh_deployment, **unreachable_environment(prefix))

    assert result.returncode != 0
    assert not result.stdout.strip()
    assert not persisted_key_path(fresh_deployment).exists()


def test_a_database_that_never_answers_refuses_within_the_timeout(
    fresh_deployment: Path, stalled_database_port: int
):
    """Refuse on the bound, not just on a connection the kernel rejects outright.

    A side-car started while its database is still coming up sees this shape
    rather than a refusal, and it is the one that could hang the container
    start indefinitely.
    """
    result = run_helper(
        fresh_deployment, **unreachable_environment("SEP", stalled_database_port)
    )

    assert result.returncode != 0
    assert not result.stdout.strip()
    assert not persisted_key_path(fresh_deployment).exists()


def test_an_unreachable_database_is_retried_rather_than_refused_on_sight(
    fresh_deployment: Path,
):
    """Keep waiting for a database that is not up yet, which a cold start is.

    The supervised migration steps wait for postgres unboundedly, so on a first
    start the databases are routinely still coming up, which is exactly when
    the mint path runs. A refused connection fails instantly, so refusing on
    the first error would kill the container in the ordinary case rather than
    an exceptional one. Refusing only after the bound is what distinguishes the
    two, and it is visible in the wall clock.
    """
    started = time.monotonic()

    result = run_helper(
        fresh_deployment,
        SEP_ENCRYPTION_PROBE_TIMEOUT=str(RETRIED_PROBE_TIMEOUT),
        **unreachable_environment("SEP"),
    )
    elapsed = time.monotonic() - started

    assert result.returncode != 0
    assert elapsed >= RETRIED_PROBE_TIMEOUT
    assert not persisted_key_path(fresh_deployment).exists()


def test_the_unreachable_refusal_does_not_send_the_operator_after_a_backup(
    fresh_deployment: Path,
):
    """Say the database is unreachable, not that a key needs restoring.

    A database still starting is the common cause here, and the ciphertext
    remedy (restore the key from a backup of the state volume) is both
    inapplicable and expensive to act on.
    """
    result = run_helper(fresh_deployment, **unreachable_environment("SEP"))

    assert result.returncode != 0
    assert "SEP_DB_HOST" in result.stderr
    assert "backup" not in result.stderr


def test_an_unparseable_stored_value_refuses_the_mint(tmp_path: Path):
    """Fail closed on a value the probe cannot decode, which may hide a token."""
    create_database(tmp_path, DATABASE_FILENAMES["SEP"], "a-plain-value")
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])
    engine = create_engine(f"sqlite:///{tmp_path / DATABASE_FILENAMES['SEP']}")
    with engine.begin() as connection:
        # Rewritten after the fact rather than inserted: the JSON column would
        # encode an unparseable Python string into perfectly parseable JSON.
        connection.exec_driver_sql("UPDATE settingoverride SET value = '{not json'")
    engine.dispose()

    result = run_helper(tmp_path)

    assert result.returncode != 0
    assert not result.stdout.strip()


def test_an_unwritable_state_directory_never_serves_a_key(fresh_deployment: Path):
    """Exit non-zero rather than serve a key the next start cannot read back.

    A key that serves one run and is re-minted on the next orphans every row
    written under it, so an unpersistable key is worse than no key at all.
    """
    state = fresh_deployment / "state"
    state.mkdir()
    state.chmod(0o500)

    result = run_helper(fresh_deployment)

    assert result.returncode != 0
    assert not result.stdout.strip()


def test_two_concurrent_starts_converge_on_one_key(fresh_deployment: Path):
    """Serialise racing starts, so neither writes rows the other cannot read.

    Two side-cars sharing an initially empty state volume both observe no key.
    Atomic replacement alone would still leave them holding different values;
    the lock plus the re-read under it is what makes them agree.
    """

    async def both() -> list[subprocess.CompletedProcess[str]]:
        return list(
            await asyncio.gather(
                asyncio.to_thread(run_helper, fresh_deployment),
                asyncio.to_thread(run_helper, fresh_deployment),
            )
        )

    first, second = asyncio.run(both())

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout.strip() == second.stdout.strip()
    assert (
        persisted_key_path(fresh_deployment).read_text(encoding="utf-8")
        == first.stdout.strip()
    )


def test_a_peer_holding_the_state_lock_blocks_the_mint(fresh_deployment: Path):
    """Wait for a peer's turn rather than probing and minting beside it.

    The convergence test above cannot see this by itself: because
    :func:`resolve` returns the value re-read from disk, an unlocked
    interleaving of write-write-read-read still converges, so deleting the lock
    leaves that test roughly a coin flip. Holding the lock from outside is what
    makes the dependence on it observable at all.
    """
    lock_path = fresh_deployment / "state" / helper.LOCK_FILENAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        with pytest.raises(subprocess.TimeoutExpired):
            run_helper(fresh_deployment, timeout=BLOCKED_RUN_SECONDS)

    assert not persisted_key_path(fresh_deployment).exists()


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(ciphertext(), id="scalar"),
        pytest.param([{"ROUTING_KEY": ciphertext()}], id="nested-in-list"),
        pytest.param({"a": {"b": ciphertext()}}, id="nested-in-mapping"),
        pytest.param([["deep", ciphertext()]], id="nested-in-nested-list"),
    ],
)
def test_ciphertext_is_found_at_every_json_position(value: Any):
    """Walk the decoded value rather than testing the row, which is a container."""
    assert helper.contains_ciphertext(value)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("a-plain-value", id="scalar"),
        pytest.param([{"PROVIDER": "pagerduty"}], id="nested-in-list"),
        pytest.param({"a": {"b": "c"}}, id="nested-in-mapping"),
        pytest.param(None, id="null"),
        pytest.param(42, id="number"),
        pytest.param([], id="empty-list"),
    ],
)
def test_a_value_with_no_token_is_not_read_as_ciphertext(value: Any):
    """Leave a plaintext deployment mintable, which is the common case."""
    assert not helper.contains_ciphertext(value)


def test_the_minted_key_matches_what_the_makefile_generates():
    """Mint the key the documented ``make encryption-key`` recipe produces.

    Both build it from 32 random bytes through the URL-safe alphabet, so a
    key minted here and one generated by hand are interchangeable.
    """
    minted = helper.mint_key()

    assert len(base64.urlsafe_b64decode(minted)) == helper.KEY_BYTES
    assert not is_encrypted(minted)


def test_a_corrupted_persisted_key_is_refused_rather_than_served(
    fresh_deployment: Path,
):
    """Report a state file the cipher cannot use, instead of passing it on.

    Serving it exits 0 and hands every supervised program a key the settings
    validator rejects, which is precisely the illegible failure this helper
    exists to replace: five children crash-looping and nothing from PID 1
    saying why.
    """
    run_helper(fresh_deployment)
    persisted_key_path(fresh_deployment).write_text(
        "not-a-fernet-key", encoding="utf-8"
    )

    result = run_helper(fresh_deployment)

    assert result.returncode != 0
    assert not result.stdout.strip()
    assert "ENCRYPTION_KEY" in result.stderr


def test_the_helper_reaches_the_image():
    """Assert the helper is copied in; bundle.tgz carries no sidecar/ file.

    A missing ``COPY`` surfaces only as a container that dies on start, with
    the entrypoint's command substitution reporting a missing file rather than
    anything about encryption.
    """
    containerfile = SIDECAR_DIR / "Containerfile.sidecar"

    assert "./sidecar/encryption_key.py ./encryption_key.py" in containerfile.read_text(
        encoding="utf-8"
    )


def test_the_refusal_names_the_state_directory_and_the_restore_path(tmp_path: Path):
    """Say what an operator has to do, which supervisord's status cannot show."""
    create_database(tmp_path, DATABASE_FILENAMES["SEP"], ciphertext())
    create_database(tmp_path, DATABASE_FILENAMES["INVENTORY"])
    create_database(tmp_path, DATABASE_FILENAMES["TASKS"])

    result = run_helper(tmp_path)

    assert "ENCRYPTION_KEY" in result.stderr
    assert str(tmp_path / "state") in result.stderr


def test_no_diagnostic_is_written_to_the_channel_the_key_is_read_from(
    fresh_deployment: Path,
):
    """Keep stdout to the key alone, which the entrypoint captures wholesale."""
    result = run_helper(fresh_deployment)

    assert result.returncode == 0, result.stderr
    assert result.stdout.count("\n") == 1
    persisted = persisted_key_path(fresh_deployment).read_text(encoding="utf-8")
    assert result.stdout == f"{persisted}\n"
