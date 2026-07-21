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

"""Define tests for celery-beat scheduler engine pool sizing (engine 5).

The 5th engine lives inside ``sqlalchemy_celery_beat``. SEP's beat runs on the
*forked* path (the after-fork hook flips ``session_manager.forked`` True in the
beat child), so the tests exercise that path — a test against a fresh
non-forked ``SessionManager`` would silently pass against a ``NullPool`` engine
that ignores pool sizing.
"""

import pytest
from celery import Celery
from sqlalchemy.pool import NullPool
from sqlalchemy_celery_beat.session import SessionManager

from app.core.celery.config import CeleryOptions

_BROKER_URL = "redis://localhost:6379/0"
_BEAT_DBURI = "postgresql+psycopg2://u:p@h/celery"


def test_forked_path_honors_pool_options():
    """Honor the pool dict on the forked path SEP runs."""
    session_manager = SessionManager()
    session_manager.forked = True
    pool = {"pool_size": 20, "max_overflow": 5, "pool_timeout": 30}

    engine, _ = session_manager.create_session(_BEAT_DBURI, schema=None, **pool)
    try:
        assert engine.pool.size() == pool["pool_size"]
        assert engine.pool._max_overflow == pool["max_overflow"]
        assert engine.pool._timeout == pool["pool_timeout"]
    finally:
        engine.dispose()


def test_non_forked_path_rejects_max_overflow():
    """Reject max_overflow on the non-forked NullPool path — the landmine.

    ``NullPool`` rejects ``max_overflow`` (the key does not start with ``pool``,
    so the library's non-forked strip does not remove it). Standalone must
    therefore leave ``beat_engine_options`` empty.
    """
    session_manager = SessionManager()

    with pytest.raises(TypeError):
        session_manager.create_session(_BEAT_DBURI, schema=None, max_overflow=5)


def test_non_forked_path_silently_drops_pool_size_and_timeout():
    """Drop pool_size and pool_timeout silently on the non-forked path."""
    session_manager = SessionManager()

    engine, _ = session_manager.create_session(
        _BEAT_DBURI, schema=None, pool_size=20, pool_timeout=30
    )
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


def test_beat_engine_options_reach_celery_conf():
    """Propagate ``beat_engine_options`` into the Celery config via ``model_dump()``.

    ``DatabaseScheduler`` reads ``app.conf.get('beat_engine_options')``; this
    closes the config-path seam the forked-honoring test above does not (that
    one passes kwargs to ``SessionManager`` directly).
    """
    pool = {"pool_size": 20, "max_overflow": 5, "pool_timeout": 30}
    options = CeleryOptions(broker_url=_BROKER_URL, beat_engine_options=pool)

    celery_app = Celery("test", **options.model_dump())

    assert celery_app.conf.beat_engine_options == pool
