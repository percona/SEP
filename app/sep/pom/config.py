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

"""Define the PostgreSQL schema every POM table lives in.

POM's tables go in the ``sep`` database, isolated by a schema of their own rather
than by a separate database or a table-name prefix. A separate database would need
every call site to choose a connection and a second migration mechanism to maintain;
a prefix would isolate nothing.

The mechanism is SQLAlchemy's **symbolic** schema, copied from what SEP already does
for the Celery beat tables (``app/core/celery/db.py``): tables declare the *token*
``pom_schema``, and the engine translates it to a real name -- or to ``None``, which
means the bind's default schema. One set of table definitions therefore works on a
PostgreSQL deployment that wants the isolation and on a SQLite one that has no
schemas at all, with no branching in the models.

Two rules live here so that they cannot disagree between the app process, the Celery
worker and Alembic:

* what the token translates to (:func:`pom_schema`), and
* the map to hand an engine (:func:`pom_schema_translate_map`).

Nothing in this module touches ``sep_settings`` at import time. The bind is passed
in by the caller instead, because the callers -- the engine, the migration
environment, the migrations -- all hold it already, and because reaching for the
lazy settings proxy while it is still constructing is how the Celery config grew its
own warning against exactly that.
"""

__all__ = [
    "POM_SCHEMA_SYMBOL",
    "PomSettings",
    "pom_schema",
    "pom_schema_translate_map",
    "pom_settings",
]

from typing import ClassVar

from app.core.config import BaseYamlSettings
from app.core.db.config import DatabaseOptions
from app.core.utils.fields import AsyncDatabaseEngine

#: The symbolic name POM's tables declare. Never a real schema: every bind either
#: translates it to :attr:`PomSettings.SCHEMA` or to ``None``. It is spelled as a
#: literal in the models -- Alembic loads those without the package ``__init__``, so
#: they cannot import this module -- which is the same trade ``sqlalchemy_celery_beat``
#: makes with ``celery_schema``.
POM_SCHEMA_SYMBOL = "pom_schema"

#: Binds that have a schema concept POM can use. PostgreSQL alone: SQLite has no
#: schemas short of an ``ATTACH``, and MySQL's "schema" *is* a database, so honouring
#: the setting there would silently scatter POM's tables into a second database that
#: nothing provisions.
_SCHEMA_CAPABLE = frozenset({AsyncDatabaseEngine.POSTGRESQL})


class PomSettings(BaseYamlSettings):
    """Configure what every POM app shares.

    :cvar SETTINGS_PREFIXES: Places this section under ``SEP.POM``.
    :param SCHEMA: The schema POM's tables live in on a bind that has schemas.
        ``None`` puts them in the default schema, which is what a deployment that
        does not want the isolation asks for. Ignored on binds without schemas --
        see :func:`pom_schema`.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["SEP", "POM"]

    SCHEMA: str | None = "pom"


pom_settings: PomSettings = PomSettings()


def pom_schema(database: DatabaseOptions) -> str | None:
    """Resolve the token for one bind.

    :param database: The database options of the bind POM's tables live on --
        ``sep_settings.DATABASE`` in every current caller.
    :return: The schema name, or ``None`` for the bind's default schema.
    """
    if database.ENGINE not in _SCHEMA_CAPABLE:
        return None
    return pom_settings.SCHEMA


def pom_schema_translate_map(database: DatabaseOptions) -> dict[str, str | None]:
    """Build the ``schema_translate_map`` an engine or connection needs.

    Apply it to every bind that POM's tables are created or queried on. Without it a
    query naming the token reaches the database as a literal ``pom_schema.<table>``,
    which fails on PostgreSQL as an undefined schema and on SQLite as an unknown
    database -- and it fails at *statement* time, so the table appears to exist and
    every use of it breaks.

    ``execution_options`` replaces an engine's map wholesale rather than merging, so
    a bind that also carries other tokens (the tests route ``None`` into a per-worker
    schema, for one) must combine the entries itself.

    :param database: The database options of the bind.
    :return: A single-entry map from the token to its resolved schema.
    """
    return {POM_SCHEMA_SYMBOL: pom_schema(database)}
