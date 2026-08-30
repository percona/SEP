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

"""Add the external-identity alias and identity-link decision tables

Revision ID: 3c39abf7a429
Revises: 5c93a28faa5f
Create Date: 2026-08-28 21:04:55.703938

A PMM ``register --force`` cascade-removes a node and recreates it under a new
UUID, so the inventory mirror ends up with two rows describing one machine.
These two tables carry the recovery path: ``externalidentityalias`` binds an
upstream identifier to a row over a validity interval, and
``identitylinkdecision`` logs what an operator decided about a candidate
pairing.

Both are append-only, so neither carries a unique index. That is load-bearing
rather than an omission: closure is expressed by appending a superseding
record, and ``BaseSQLModelManager.save`` rebuilds equality filters from every
unique index and would refuse the second, legitimate row.

``entity_id`` carries no foreign key because it is polymorphic over ``node``
and ``service``, and because the audit trail must outlive a row the tombstone
collection deletes.

Every enum column is non-native and carries its own CHECK, so a future member
needs no PostgreSQL type alteration and none of them shares a type object with
the ``node.source`` column. ``create_constraint=True`` is what emits the CHECK
at all: SQLAlchemy does not derive one from ``native_enum=False`` alone, so
omitting it would leave the columns accepting arbitrary strings.

Each CHECK carries an explicit, table-qualified name rather than the one
SQLAlchemy derives from the enum class. MySQL scopes CHECK constraint names to
the **schema**, not the table, so the derived name would have both tables
declaring ``retirableentityname`` over their ``entity_type`` column and the
second ``CREATE TABLE`` would fail with error 3822. PostgreSQL and SQLite scope
the name per table and accept the collision, which is why it has to be reasoned
about here rather than discovered from the suite. Naming them explicitly also
keeps ``alias_source`` clear of ``node.source``, which would collide the same
way if it were ever given the CHECK it should have.

Additive throughout: no existing table is touched, and there is no data
migration, so the downgrade simply drops both tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = "3c39abf7a429"
down_revision: Union[str, Sequence[str], None] = "5c93a28faa5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "externalidentityalias",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "entity_type",
            sa.Enum(
                "NODE",
                "SERVICE",
                "SCHEMA",
                "TABLE",
                name="alias_entity_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "PMM",
                name="alias_source",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("external_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "linkage_method",
            sa.Enum(
                "OPERATOR_CONFIRMATION",
                "OPERATOR_UNLINK",
                name="alias_linkage_method",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("principal", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_alias_entity",
        "externalidentityalias",
        ["entity_type", "entity_id"],
        unique=False,
    )
    op.create_index(
        "ix_alias_source_external_id",
        "externalidentityalias",
        ["source", "external_id"],
        unique=False,
    )
    op.create_table(
        "identitylinkdecision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "entity_type",
            sa.Enum(
                "NODE",
                "SERVICE",
                "SCHEMA",
                "TABLE",
                name="link_decision_entity_type",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("predecessor_id", sa.Integer(), nullable=False),
        sa.Column("successor_id", sa.Integer(), nullable=False),
        sa.Column(
            "decision",
            sa.Enum(
                "CONFIRMED",
                "REJECTED",
                "UNLINKED",
                name="link_decision_decision",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("principal", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "predecessor_external_id",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=True,
        ),
        sa.Column("predecessor_retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_link_decision_pair",
        "identitylinkdecision",
        ["entity_type", "predecessor_id", "successor_id"],
        unique=False,
    )
    op.create_index(
        "ix_link_decision_successor",
        "identitylinkdecision",
        ["entity_type", "successor_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_link_decision_successor", table_name="identitylinkdecision")
    op.drop_index("ix_link_decision_pair", table_name="identitylinkdecision")
    op.drop_table("identitylinkdecision")
    op.drop_index("ix_alias_source_external_id", table_name="externalidentityalias")
    op.drop_index("ix_alias_entity", table_name="externalidentityalias")
    op.drop_table("externalidentityalias")
