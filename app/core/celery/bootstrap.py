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

"""Create the Celery beat schedule tables ahead of the processes that read them.

The ``sqlalchemy_celery_beat`` tables are created by no alembic revision in any of
SEP's three migration tracks: the library builds them itself, from
:meth:`sqlalchemy_celery_beat.session.SessionManager.prepare_models`, which
:class:`~sqlalchemy_celery_beat.schedulers.DatabaseScheduler` reaches on beat's
own startup. Every service that seeds periodic tasks during its lifespan
(:func:`app.core.celery.utils.init_periodic_tasks_db`) therefore reads tables
whose only creator is a process ordered *behind* it, and on a database with no
schema the read fails.

Driving the library's own bootstrap from a step ordered ahead of those services
breaks the cycle while leaving the tables the library's to define — nothing here
declares their shape. This module is kept beside :mod:`app.core.celery.db` rather
than inside it so importing it does not construct that module's asynchronous
engine, which resolves the same setting through a driver
:meth:`~sqlalchemy_celery_beat.session.SessionManager.prepare_models` cannot use.
"""

import argparse
import logging
import logging.config
import sys
from collections.abc import Sequence
from time import monotonic, sleep
from typing import Any

from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy_celery_beat.session import SessionManager

from app.core.config import settings

logger = logging.getLogger(__name__)

STORE_READINESS_POLL_INTERVAL = 1.0
"""Seconds between connection attempts while the beat store is unreachable."""

STORE_CONNECT_TIMEOUT = 5
"""Seconds for each TCP connect attempt when a readiness deadline is set.

The deadline is only consulted after ``engine.connect()`` returns. A host that
silently drops packets otherwise leaves the call blocked on the OS TCP timeout
(often minutes), so ``make migrate`` would still hang well past its bound.
``psycopg2``'s ``connect_timeout`` caps each attempt; kept strictly below the
migrate recipe's 60s budget so several polls fit inside it. SQLite has no TCP
connect and rejects the argument, so it is applied only for PostgreSQL.
"""


def _session_kwargs_for_deadline(
    dburi: str, deadline_seconds: float | None
) -> dict[str, Any]:
    """Return ``create_session`` kwargs that bound each connect under a deadline.

    :param dburi: The resolved beat-store URL.
    :param deadline_seconds: The caller's wall-clock bound, or ``None`` when
        unbounded (side-car).
    :return: ``connect_args`` for PostgreSQL when a deadline is set; otherwise
        an empty dict so the unbounded path is unchanged.
    """
    if deadline_seconds is None:
        return {}
    if make_url(dburi).get_backend_name() != "postgresql":
        return {}
    connect_timeout = max(1, min(STORE_CONNECT_TIMEOUT, int(deadline_seconds)))
    return {"connect_args": {"connect_timeout": connect_timeout}}


def _wait_for_store(engine: Engine, *, deadline_seconds: float | None = None) -> None:
    """Block until the beat store accepts a connection.

    The side-car's three alembic one-shots wait on ``SEP_DB_HOST``/``SEP_DB_PORT``
    in the shell, because that is the database they upgrade. The beat store is
    whatever ``CELERY.beat_dburi`` resolves to, and a deployment may point it at a
    separate database, so readiness is probed against the URL this process will
    actually dial rather than against a host named in the program table.

    By default the wait is unbounded, matching those three shell loops. A bound
    that expired while the store was merely slow would leave the side-car's
    one-shot sentinel permanently unwritten, gating every program behind it for
    the life of the container. Callers that can be re-run — such as
    ``make migrate`` — may pass ``deadline_seconds`` so a persistent
    ``OperationalError`` (including a rejected password) fails the command
    instead of hanging indefinitely.

    When a deadline is set, the engine is built with a per-attempt
    ``connect_timeout`` (see :data:`STORE_CONNECT_TIMEOUT`) so a firewalled or
    unroutable host cannot block past the bound on a single TCP handshake.
    ``prepare_models`` reuses that engine, so its connects inherit the same cap.

    ``prepare_models`` retries too, but only for the check-then-create race it was
    written for: ten attempts with sub-second backoff, which a database that has
    not finished starting outlasts.

    :param engine: The synchronous engine for the resolved beat store.
    :param deadline_seconds: Wall-clock seconds to keep retrying
        ``OperationalError``s. ``None`` (the default) waits without a bound.
    :raises TimeoutError: When ``deadline_seconds`` elapses while the store still
        refuses connections with ``OperationalError``.
    :raises DBAPIError: On a connection failure that is not an
        ``OperationalError``, which is raised on the first attempt rather than
        retried — only an ``OperationalError`` is treated as "not up yet".
    """
    deadline = None if deadline_seconds is None else monotonic() + deadline_seconds
    while True:
        try:
            with engine.connect():
                return
        except OperationalError:
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError(
                    f"Celery beat store at {engine.url.host}:{engine.url.port} "
                    f"did not become reachable within {deadline_seconds} seconds"
                ) from None
            # Host and port only: the resolved URL carries the store's password.
            logger.info(
                "Waiting for the Celery beat store at %s:%s",
                engine.url.host,
                engine.url.port,
            )
            sleep(STORE_READINESS_POLL_INTERVAL)


def bootstrap_beat_schema(*, deadline_seconds: float | None = None) -> None:
    """Create the ``sqlalchemy_celery_beat`` schedule tables if they are absent.

    The store and schema are resolved exactly as
    :meth:`sqlalchemy_celery_beat.schedulers.DatabaseScheduler.__init__` resolves
    them, so beat and this step cannot disagree about where the tables belong.
    ``prepare_models`` checks before it creates, so a store that already carries
    them is left alone.

    The scheduler's pool options are deliberately **not** forwarded. On this
    non-forked path the library pins ``NullPool`` and drops every
    ``pool``-prefixed key, so such an option is either ignored or — for a key
    outside that prefix, such as ``max_overflow`` — rejected outright by
    ``create_engine``. Neither outcome can configure anything, and the second
    would fail this step on a documented, validated setting.

    A readiness ``deadline_seconds`` does forward a driver ``connect_timeout`` for
    PostgreSQL so each dial is capped; that is unrelated to the pool options
    above and is omitted when the wait is unbounded.

    :param deadline_seconds: Optional wall-clock bound forwarded to the store
        readiness wait. ``None`` leaves the wait unbounded (side-car one-shot).
    :raises TimeoutError: When a supplied ``deadline_seconds`` elapses while the
        store is still unreachable.
    :raises DBAPIError: When the store refuses a connection for a reason other
        than not being up yet, or when creating the tables fails after the
        library has exhausted its own retries. The family is ``DBAPIError``
        rather than ``DatabaseError`` because the first case surfaces as
        ``InterfaceError``, a sibling of ``DatabaseError`` rather than one of
        its subclasses.
    :raises ArgumentError: When the resolved URL is malformed, or names a dialect
        whose driver is not installed. The engine is built before the wait, so
        this surfaces immediately.
    """
    manager = SessionManager()
    engine, _ = manager.create_session(
        settings.CELERY.beat_dburi,
        schema=settings.CELERY.beat_schema,
        **_session_kwargs_for_deadline(settings.CELERY.beat_dburi, deadline_seconds),
    )
    try:
        _wait_for_store(engine, deadline_seconds=deadline_seconds)
        manager.prepare_models(engine, schema=settings.CELERY.beat_schema)
    finally:
        engine.dispose()


def _build_arg_parser() -> argparse.ArgumentParser:
    """Return the CLI parser for the beat-schema bootstrap entry point.

    :return: A parser exposing optional ``--deadline-seconds``.
    """
    parser = argparse.ArgumentParser(
        description="Create the Celery beat schedule tables if they are absent."
    )
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Wall-clock seconds to wait for the beat store before failing. "
            "Omit to wait without a bound (side-car migrate-beat)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the bootstrap, configuring logging for a freshly spawned process.

    Supervisord starts this in a process that has run no ``dictConfig``, and the
    wait's own log lines are the only account an operator gets of why the schema
    step has not finished. A failure is deliberately left to propagate: the
    non-zero exit is what keeps the caller's sentinel unwritten.

    ``--deadline-seconds`` is optional so the side-car's one-shot invocation
    stays unbounded; ``make migrate`` passes a bound so a persistent store
    failure fails the command instead of hanging.

    :param argv: CLI arguments. ``None`` means no flags (unbounded wait), matching
        a bare ``python -m`` / programmatic call; ``__main__`` passes
        ``sys.argv[1:]``.
    :raises TimeoutError: When a supplied deadline elapses while the store is
        still unreachable.
    :raises SQLAlchemyError: When the tables cannot be created, or the store
        refuses a connection for a reason other than not being up yet.
    """
    args = _build_arg_parser().parse_args([] if argv is None else argv)
    logging.config.dictConfig(settings.LOGGING_CONFIG)
    bootstrap_beat_schema(deadline_seconds=args.deadline_seconds)
    logger.info("Celery beat schedule tables are present.")


if __name__ == "__main__":
    main(sys.argv[1:])
