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

"""Define the PostgreSQL schema every OM table lives in.

OM's tables go in the ``sep`` database, isolated by a schema of their own rather
than by a separate database or a table-name prefix. A separate database would need
every call site to choose a connection and a second migration mechanism to maintain;
a prefix would isolate nothing.

The mechanism is SQLAlchemy's **symbolic** schema, copied from what SEP already does
for the Celery beat tables (``app/core/celery/db.py``): tables declare the *token*
``om_schema``, and the engine translates it to a real name -- or to ``None``, which
means the bind's default schema. One set of table definitions therefore works on a
PostgreSQL deployment that wants the isolation and on a SQLite one that has no
schemas at all, with no branching in the models.

The token's real name is a plain deployment setting rather than something computed
here: ``sep_settings.DATABASE.SCHEMA_TRANSLATE_MAP`` (``app/core/db/config.py``) is
the single core-owned map every symbolic schema token resolves through, applied to
the engine by ``create_app_async_engine`` and to Alembic's connection by
``app/sep/migrations/env.py``. Neither of those imports this module -- they only
know the generic map -- so what lives here is just the token's name and a lookup
into that map for callers, like the OM migration, that need the resolved schema
for raw DDL.
"""

__all__ = ["OM_SCHEMA_SYMBOL", "om_schema"]

from app.core.db.config import DatabaseOptions

#: The symbolic name OM's tables declare. Never a real schema: every bind either
#: translates it to a real name or to ``None`` via ``sep_settings.DATABASE.
#: SCHEMA_TRANSLATE_MAP``. It is spelled as a literal in the models -- Alembic loads
#: those without the package ``__init__``, so they cannot import this module --
#: which is the same trade ``sqlalchemy_celery_beat`` makes with ``celery_schema``.
OM_SCHEMA_SYMBOL = "om_schema"


def om_schema(database: DatabaseOptions) -> str | None:
    """Resolve the token to its real schema name for one bind.

    :param database: The database options of the bind OM's tables live on --
        ``sep_settings.DATABASE`` in every current caller.
    :return: The schema name, or ``None`` for the bind's default schema.
    """
    return database.SCHEMA_TRANSLATE_MAP.get(OM_SCHEMA_SYMBOL)
