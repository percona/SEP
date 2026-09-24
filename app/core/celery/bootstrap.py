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
PMM Extensions' three migration tracks: the library builds them itself, from
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

import logging
import logging.config
from time import sleep

from sqlalchemy import or_
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy_celery_beat.models import PeriodicTask
from sqlalchemy_celery_beat.session import SessionManager

from app.core.config import settings

logger = logging.getLogger(__name__)

STORE_READINESS_POLL_INTERVAL = 1.0
"""Seconds between connection attempts while the beat store is unreachable."""


def _wait_for_store(engine: Engine) -> None:
    """Block until the beat store accepts a connection.

    The side-car's three alembic one-shots wait on ``EXTENSIONS_DB_HOST``/``EXTENSIONS_DB_PORT``
    in the shell, because that is the database they upgrade. The beat store is
    whatever ``CELERY.beat_dburi`` resolves to, and a deployment may point it at a
    separate database, so readiness is probed against the URL this process will
    actually dial rather than against a host named in the program table.

    The wait is unbounded, matching those three shell loops. A bounded one could
    expire while the store was merely slow, and the caller runs as a one-shot that
    is never re-run, so its sentinel could then never appear — leaving every
    program gated on it waiting for the life of the container. What bounds the
    observable behaviour instead is the gate in front of each API program, and the
    healthcheck, which reports the missing sentinel either way.

    ``prepare_models`` retries too, but only for the check-then-create race it was
    written for: ten attempts with sub-second backoff, which a database that has
    not finished starting outlasts.

    :param engine: The synchronous engine for the resolved beat store.
    :raises DBAPIError: On a connection failure that is not an
        ``OperationalError``, which is raised on the first attempt rather than
        retried — only an ``OperationalError`` is treated as "not up yet".
    """
    while True:
        try:
            with engine.connect():
                return
        except OperationalError:
            # Host and port only: the resolved URL carries the store's password.
            logger.info(
                "Waiting for the Celery beat store at %s:%s",
                engine.url.host,
                engine.url.port,
            )
            sleep(STORE_READINESS_POLL_INTERVAL)


PRE_RENAME_NAME_PREFIX = "sep__"
"""The prefix system schedules were seeded under before the rename. A frozen literal."""

NAME_PREFIX = "extensions__"
"""The prefix :func:`app.core.celery.utils.init_periodic_tasks_db` seeds them under."""

PRE_RENAME_TASK_PREFIX = "app.sep."
"""The package the scheduled task paths named before the rename. A frozen literal."""

TASK_PREFIX = "app.extensions."
"""The package the scheduled task paths name now."""


def move_pre_rename_periodic_tasks(session_factory: sessionmaker[Session]) -> int:
    """Move stored schedules forward from their pre-rename names and task paths.

    A beat row stores both the schedule's name, seeded under a prefix, and the
    dotted path of the task it fires, a module path under the package. The
    rename moved both. Seeding reconciles only rows under the current prefix, so
    a row left under the old one would keep firing a task path that no longer
    resolves, alongside the new row seeded beside it. Renaming the row in place
    keeps its schedule state instead. A row whose new name was already seeded is
    the duplicate, and is deleted.

    The rows are changed through the ORM, so the library's change listener tells
    a running scheduler to reload. Every later run finds nothing to move.

    :param session_factory: Sessions bound to the resolved beat store.
    :return: How many rows were renamed or deleted.
    """
    with session_factory() as session:
        stale = (
            session.query(PeriodicTask)
            .filter(
                or_(
                    PeriodicTask.name.startswith(
                        PRE_RENAME_NAME_PREFIX, autoescape=True
                    ),
                    PeriodicTask.task.startswith(
                        PRE_RENAME_TASK_PREFIX, autoescape=True
                    ),
                )
            )
            .all()
        )
        if not stale:
            return 0
        seeded = {
            name
            for (name,) in session.query(PeriodicTask.name).filter(
                PeriodicTask.name.startswith(NAME_PREFIX, autoescape=True)
            )
        }
        for row in stale:
            if row.name.startswith(PRE_RENAME_NAME_PREFIX):
                name = NAME_PREFIX + row.name.removeprefix(PRE_RENAME_NAME_PREFIX)
                if name in seeded:
                    session.delete(row)
                    continue
                row.name = name
            if row.task.startswith(PRE_RENAME_TASK_PREFIX):
                row.task = TASK_PREFIX + row.task.removeprefix(PRE_RENAME_TASK_PREFIX)
        session.commit()
    logger.info("Moved %d Celery beat schedules to their renamed names.", len(stale))
    return len(stale)


def bootstrap_beat_schema() -> None:
    """Create the ``sqlalchemy_celery_beat`` schedule tables if they are absent.

    Then move any schedule stored under its pre-rename name forward, through
    :func:`move_pre_rename_periodic_tasks`, before a seeding service reads it.

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
    engine, session_factory = manager.create_session(
        settings.CELERY.beat_dburi,
        schema=settings.CELERY.beat_schema,
    )
    try:
        _wait_for_store(engine)
        manager.prepare_models(engine, schema=settings.CELERY.beat_schema)
        move_pre_rename_periodic_tasks(session_factory)
    finally:
        engine.dispose()


def main() -> None:
    """Run the bootstrap, configuring logging for a freshly spawned process.

    Supervisord starts this in a process that has run no ``dictConfig``, and the
    wait's own log lines are the only account an operator gets of why the schema
    step has not finished. A failure is deliberately left to propagate: the
    non-zero exit is what keeps the caller's sentinel unwritten.

    :raises SQLAlchemyError: When the tables cannot be created, or the store
        refuses a connection for a reason other than not being up yet.
    """
    logging.config.dictConfig(settings.LOGGING_CONFIG)
    bootstrap_beat_schema()
    logger.info("Celery beat schedule tables are present.")


if __name__ == "__main__":
    main()
