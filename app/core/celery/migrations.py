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

"""Keep the library-owned Celery beat tables out of PMM Extensions' Alembic autogenerate.

The six ``sqlalchemy_celery_beat`` schedule tables belong to the library, not to
any of PMM Extensions' three Alembic tracks. No revision creates them; the library builds
them itself, driven by :mod:`app.core.celery.bootstrap`. They are declared on the
library's own declarative base, so they are absent from the ``SQLModel.metadata``
every track passes as ``target_metadata``. Where the beat store resolves to a
track's own database under the default schema, autogenerate therefore reads that
store as one that has lost six tables, and proposes dropping them.

That coincidence is the side-car's configuration rather than the shipped
``development`` profile, which gives beat a database of its own. So a green
migration check under the default profile says nothing about whether this filter
works; the per-track tests that build the coincident state are what cover it.

The filter names those tables specifically rather than suppressing every
unmatched reflected object, so a genuinely removed PMM Extensions table is still detected.
"""

from sqlalchemy.sql.schema import SchemaItem
from sqlalchemy_celery_beat.session import ModelBase

BEAT_TABLE_NAMES: frozenset[str] = frozenset(
    table.name for table in ModelBase.metadata.tables.values()
)
"""Bare names of the tables ``sqlalchemy_celery_beat`` declares.

Derived from the library's own metadata rather than written out, so a schedule
type the library adds is covered without an edit here, and a future PMM Extensions table
whose name merely begins with ``celery_`` is not swallowed.

``metadata.tables`` is keyed by the *logical* schema-qualified name
(``celery_schema.celery_periodictask``), because the models carry
``__table_args__ = {"schema": "celery_schema"}`` and the library translates that
at connect time through ``schema_translate_map``. Autogenerate reflects the bare
name, so those keys would match nothing: read ``Table.name``.
"""


def include_object(
    object_: SchemaItem,  # noqa: ARG001
    name: str | None,
    type_: str,
    reflected: bool,  # noqa: FBT001
    compare_to: SchemaItem | None,  # noqa: ARG001
) -> bool:
    """Report whether Alembic's autogenerate sweep should consider an object.

    The parameter names are Alembic's own, and every argument arrives
    positionally, so the two the decision does not read are kept rather than
    renamed.

    :param object_: The schema item being considered. Unused: the decision needs
        only the name and provenance.
    :param name: The object's name, bare rather than schema-qualified.
    :param type_: The kind of object, such as ``"table"`` or ``"column"``.
    :param reflected: Whether the object came from database reflection rather
        than from the target metadata. Only a reflected table can be excluded,
        so a PMM Extensions model declaring one of these names is left alone.
    :param compare_to: The object being compared against. Unused.
    :return: ``False`` for a reflected beat table, ``True`` for everything else.
    """
    return not (type_ == "table" and reflected and name in BEAT_TABLE_NAMES)
