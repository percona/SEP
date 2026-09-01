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

"""Cover the Celery beat schedule-table bootstrap the side-car runs before its APIs."""

import logging
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import InterfaceError, OperationalError

from app.core.celery import bootstrap
from app.core.celery.config import PoolEngineOptions
from app.core.config import settings

BEAT_TABLES = frozenset(
    {
        "celery_periodictask",
        "celery_periodictaskchanged",
        "celery_intervalschedule",
        "celery_crontabschedule",
        "celery_solarschedule",
        "celery_clockedschedule",
    }
)
"""Every table ``sqlalchemy_celery_beat`` reads, including the one the bug names."""

OVERRIDDEN_STORE = "postgresql+psycopg2://beat:{password}@beat-store.example:6543/beat"
"""A beat store deliberately unlike the SEP database, for the override cases."""

REFUSALS_BEFORE_THE_STORE_ANSWERS = 2
"""Connection attempts the flaky-store cases turn away before accepting one.

Bounded so the readiness loop is entered more than once — the wait itself has no
bound, so a stand-in that refused forever would hang the suite rather than fail.
"""


class RecordingSessionManager:
    """Record what the bootstrap hands the library, over the URL it was given.

    Substituted for ``SessionManager`` so the two calls the bootstrap makes can be
    asserted without a reachable store. ``create_engine`` opens no connection, so
    the engine handed back carries the resolved URL for the readiness probe to
    report while touching nothing.
    """

    def __init__(self) -> None:
        """Start with no recorded calls."""
        self.create_session_calls: list[tuple[str, str | None, dict[str, Any]]] = []
        self.prepare_models_calls: list[tuple[Engine, str | None]] = []

    def create_session(
        self, dburi: str, schema: str | None = None, **kwargs: Any
    ) -> tuple[Engine, None]:
        """Record the resolution arguments and return an engine for that URL.

        :param dburi: The store URL the bootstrap resolved.
        :param schema: The schema the bootstrap resolved.
        :param kwargs: Any engine options the bootstrap chose to forward.
        :return: An unconnected engine and a placeholder for the session maker.
        """
        self.create_session_calls.append((dburi, schema, kwargs))
        return create_engine(dburi), None

    def prepare_models(self, engine: Engine, schema: str | None = None) -> None:
        """Record the engine and schema the table creation was asked for.

        :param engine: The engine the bootstrap built.
        :param schema: The schema the bootstrap resolved.
        """
        self.prepare_models_calls.append((engine, schema))


@pytest.fixture
def sqlite_beat_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the beat store at an empty SQLite file for the length of one test.

    :param tmp_path: The per-test temporary directory.
    :param monkeypatch: The attribute patcher.
    :return: The store URL the bootstrap will resolve.
    """
    url = f"sqlite:///{tmp_path / 'schedule.db'}"
    monkeypatch.setattr(settings.CELERY, "beat_dburi", url)
    monkeypatch.setattr(settings.CELERY, "beat_schema", None)
    return url


@pytest.fixture
def recording_manager(monkeypatch: pytest.MonkeyPatch) -> RecordingSessionManager:
    """Swap the library's session manager for a recording stand-in.

    :param monkeypatch: The attribute patcher.
    :return: The instance the bootstrap will drive.
    """
    manager = RecordingSessionManager()
    monkeypatch.setattr(bootstrap, "SessionManager", lambda: manager)
    return manager


@pytest.fixture
def store_accepts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let every connection attempt succeed without dialling anything.

    :param monkeypatch: The attribute patcher.
    """

    def connect(self: Engine, *args: Any, **kwargs: Any) -> Any:
        return nullcontext()

    monkeypatch.setattr(Engine, "connect", connect)


@pytest.fixture
def instant_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the readiness poll interval so the wait cases do not sleep.

    :param monkeypatch: The attribute patcher.
    """
    monkeypatch.setattr(bootstrap, "STORE_READINESS_POLL_INTERVAL", 0)


@pytest.fixture
def refuse_then_accept(monkeypatch: pytest.MonkeyPatch) -> Callable[[], int]:
    """Refuse a fixed number of connections, then accept every later one.

    Later attempts are answered without dialling, for the cases whose store URL
    names a host that does not exist.

    :param monkeypatch: The attribute patcher.
    :return: A callable reporting how many attempts were made.
    """
    attempts = {"count": 0}

    def connect(self: Engine, *args: Any, **kwargs: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] <= REFUSALS_BEFORE_THE_STORE_ANSWERS:
            raise OperationalError("connect", {}, Exception("starting up"))
        return nullcontext()

    monkeypatch.setattr(Engine, "connect", connect)
    return lambda: attempts["count"]


@pytest.fixture
def refuse_then_really_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[], int]:
    """Refuse a fixed number of connections, then let the real ones through.

    The table creation that follows the wait needs a genuine connection, so this
    delegates rather than standing in once the store has "come up".

    :param monkeypatch: The attribute patcher.
    :return: A callable reporting how many attempts were made.
    """
    attempts = {"count": 0}
    real_connect = Engine.connect

    def connect(self: Engine, *args: Any, **kwargs: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] <= REFUSALS_BEFORE_THE_STORE_ANSWERS:
            raise OperationalError("connect", {}, Exception("starting up"))
        return real_connect(self, *args, **kwargs)

    monkeypatch.setattr(Engine, "connect", connect)
    return lambda: attempts["count"]


def table_names(url: str) -> set[str]:
    """Return the tables present in the store at ``url``.

    :param url: A synchronous store URL.
    :return: Every table name the store carries.
    """
    engine = create_engine(url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_the_bootstrap_creates_the_schedule_tables(sqlite_beat_store: str):
    """Create every table beat reads, against a store that carries no schema.

    ``celery_intervalschedule`` is the one the reported traceback names: no
    alembic track creates it, so nothing but this step puts it there before the
    APIs seed their periodic tasks.
    """
    bootstrap.bootstrap_beat_schema()

    assert table_names(sqlite_beat_store) >= BEAT_TABLES


def test_the_bootstrap_is_idempotent(sqlite_beat_store: str):
    """Leave an already-populated store alone, as a restart or upgrade finds it."""
    bootstrap.bootstrap_beat_schema()
    bootstrap.bootstrap_beat_schema()

    assert table_names(sqlite_beat_store) >= BEAT_TABLES


def test_the_bootstrap_resolves_the_store_like_the_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    recording_manager: RecordingSessionManager,
    store_accepts: None,
):
    """Pass the scheduler's own dburi and schema to both library calls.

    ``DatabaseScheduler.__init__`` resolves the pair once and hands it to
    ``create_session`` and ``prepare_models`` alike; a bootstrap that resolved
    either differently would create the tables somewhere beat never looks.
    """
    monkeypatch.setattr(
        settings.CELERY, "beat_dburi", OVERRIDDEN_STORE.format(password="pw")
    )
    monkeypatch.setattr(settings.CELERY, "beat_schema", "beat")

    bootstrap.bootstrap_beat_schema()

    dburi, create_schema, _ = recording_manager.create_session_calls[0]
    assert dburi == settings.CELERY.beat_dburi
    assert create_schema == settings.CELERY.beat_schema
    assert recording_manager.prepare_models_calls[0][1] == settings.CELERY.beat_schema


def test_the_bootstrap_uses_the_synchronous_url(
    monkeypatch: pytest.MonkeyPatch,
    recording_manager: RecordingSessionManager,
    store_accepts: None,
):
    """Resolve the psycopg2 URL, not the asyncpg one the worker engine converts to.

    ``create_session`` calls ``create_engine``, which cannot drive an async
    driver.
    """
    monkeypatch.setattr(
        settings.CELERY, "beat_dburi", OVERRIDDEN_STORE.format(password="pw")
    )

    bootstrap.bootstrap_beat_schema()

    dburi, _, _ = recording_manager.create_session_calls[0]
    assert dburi.startswith("postgresql+psycopg2://")
    assert "asyncpg" not in dburi


def test_the_bootstrap_forwards_no_engine_options(
    monkeypatch: pytest.MonkeyPatch,
    recording_manager: RecordingSessionManager,
    store_accepts: None,
):
    """Withhold the pool options, which this path can only ignore or choke on.

    The library pins ``NullPool`` here and drops every ``pool``-prefixed key, so
    such an option configures nothing. ``max_overflow`` carries no such prefix, is
    passed straight to ``create_engine``, and is rejected outright — which would
    fail this step on a documented, validated setting.
    """
    monkeypatch.setattr(
        settings.CELERY, "beat_dburi", OVERRIDDEN_STORE.format(password="pw")
    )
    monkeypatch.setattr(
        settings.CELERY,
        "beat_engine_options",
        PoolEngineOptions(pool_size=20, max_overflow=5, pool_timeout=30),
    )

    bootstrap.bootstrap_beat_schema()

    _, _, options = recording_manager.create_session_calls[0]
    assert options == {}


def test_a_rejected_engine_option_would_fail_the_step(sqlite_beat_store: str):
    """Pin why the options are withheld: the library forwards this one verbatim.

    Guards the reasoning behind the test above — if the library ever started
    filtering ``max_overflow`` too, withholding the options would stop being
    load-bearing and this test would say so.
    """
    with pytest.raises(TypeError, match="max_overflow"):
        bootstrap.SessionManager().create_session(sqlite_beat_store, max_overflow=5)


def test_a_failed_bootstrap_is_not_swallowed(
    sqlite_beat_store: str, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
):
    """Propagate a creation failure so the one-shot lands EXITED with no sentinel.

    The sentinel is what the API gate reads, so a bootstrap that exited 0 on a
    failed create would release the APIs against the schema it did not build.
    """

    def refuse_to_create(*args: Any, **kwargs: Any) -> None:
        raise OperationalError("CREATE TABLE", {}, Exception("permission denied"))

    mocker.patch("logging.config.dictConfig")
    monkeypatch.setattr(bootstrap.SessionManager, "prepare_models", refuse_to_create)

    with pytest.raises(OperationalError):
        bootstrap.main()


def test_the_bootstrap_waits_for_a_store_that_is_not_up_yet(
    sqlite_beat_store: str,
    instant_polling: None,
    refuse_then_really_connect: Callable[[], int],
):
    """Retry a refused connection rather than failing on a store still starting.

    The library's own retry caps at ten attempts with sub-second sleeps, which
    covers its check-then-create race and not a database still booting.
    """
    bootstrap.bootstrap_beat_schema()

    assert refuse_then_really_connect() > REFUSALS_BEFORE_THE_STORE_ANSWERS
    assert table_names(sqlite_beat_store) >= BEAT_TABLES


def test_the_readiness_wait_is_not_bounded(
    sqlite_beat_store: str, instant_polling: None, monkeypatch: pytest.MonkeyPatch
):
    """Keep waiting past any fixed budget, so a slow store is not made terminal.

    ``migrate-beat`` is a one-shot supervisord never re-runs, so a wait that gave
    up would leave its sentinel unwritable for the life of the container and hold
    every gated API behind it. The three alembic siblings loop unbounded for the
    same reason.
    """
    attempts = {"count": 0}
    refusals = 250

    def connect(self: Engine, *args: Any, **kwargs: Any) -> Any:
        attempts["count"] += 1
        if attempts["count"] <= refusals:
            raise OperationalError("connect", {}, Exception("starting up"))
        return nullcontext()

    def skip_creation(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(Engine, "connect", connect)
    monkeypatch.setattr(bootstrap.SessionManager, "prepare_models", skip_creation)

    bootstrap.bootstrap_beat_schema()

    assert attempts["count"] == refusals + 1


def test_a_non_transient_connection_failure_is_not_retried(
    sqlite_beat_store: str, instant_polling: None, monkeypatch: pytest.MonkeyPatch
):
    """Surface anything that is not "not up yet" on the first attempt.

    Only ``OperationalError`` means a store that may still appear. Retrying every
    failure class would turn a misconfiguration into an unbounded wait, which is
    what now bounds this loop in place of a deadline.
    """
    attempts = {"count": 0}

    def refuse(self: Engine, *args: Any, **kwargs: Any) -> None:
        attempts["count"] += 1
        raise InterfaceError("connect", {}, Exception("driver is broken"))

    monkeypatch.setattr(Engine, "connect", refuse)

    with pytest.raises(InterfaceError):
        bootstrap.bootstrap_beat_schema()

    assert attempts["count"] == 1


def test_readiness_follows_an_overridden_store(
    monkeypatch: pytest.MonkeyPatch,
    recording_manager: RecordingSessionManager,
    instant_polling: None,
    refuse_then_accept: Callable[[], int],
    caplog: pytest.LogCaptureFixture,
):
    """Wait on the store ``CELERY__BEAT_DBURI`` names, not the SEP database.

    Pointing beat at a separate store is a documented deployment input, so a
    readiness wait keyed on ``SEP_DB_HOST`` would watch the wrong host.
    """
    monkeypatch.setattr(
        settings.CELERY, "beat_dburi", OVERRIDDEN_STORE.format(password="pw")
    )
    monkeypatch.setattr(settings.CELERY, "beat_schema", None)

    with caplog.at_level(logging.INFO, logger=bootstrap.__name__):
        bootstrap.bootstrap_beat_schema()

    assert "beat-store.example" in caplog.text
    assert "6543" in caplog.text


def test_the_store_password_never_reaches_the_log(
    monkeypatch: pytest.MonkeyPatch,
    recording_manager: RecordingSessionManager,
    instant_polling: None,
    refuse_then_accept: Callable[[], int],
    caplog: pytest.LogCaptureFixture,
):
    """Log the host and port only: the resolved store URL carries a credential."""
    password = "s3cr3t-beat-password"
    monkeypatch.setattr(
        settings.CELERY, "beat_dburi", OVERRIDDEN_STORE.format(password=password)
    )
    monkeypatch.setattr(settings.CELERY, "beat_schema", None)

    with caplog.at_level(logging.INFO, logger=bootstrap.__name__):
        bootstrap.bootstrap_beat_schema()

    assert password not in caplog.text
