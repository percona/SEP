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

"""Define tests for the app.core.celery.db module (celery worker engine, engine 4)."""

import importlib
from unittest.mock import patch

import app.core.celery.db as celery_db_module
from app.core.config import settings


def test_worker_engine_forwards_beat_engine_options():
    """Forward the configured beat pool options into the worker create_async_engine call."""
    options = {"pool_size": 20, "max_overflow": 5, "pool_timeout": 30}
    try:
        with (
            patch.object(settings.CELERY, "beat_engine_options", options),
            patch("sqlalchemy.ext.asyncio.create_async_engine") as create_engine,
        ):
            importlib.reload(celery_db_module)
            _, kwargs = create_engine.call_args
            assert {key: kwargs[key] for key in options} == options
    finally:
        importlib.reload(celery_db_module)


def test_worker_engine_omits_pool_kwargs_by_default():
    """Omit pool kwargs when beat_engine_options is empty, preserving current behavior."""
    try:
        with (
            patch.object(settings.CELERY, "beat_engine_options", {}),
            patch("sqlalchemy.ext.asyncio.create_async_engine") as create_engine,
        ):
            importlib.reload(celery_db_module)
            _, kwargs = create_engine.call_args
            assert "pool_size" not in kwargs
            assert "max_overflow" not in kwargs
            assert "pool_timeout" not in kwargs
    finally:
        importlib.reload(celery_db_module)
