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

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

from app.core.db.utils import compare_type
from app.sep.config import sep_settings
from app.sep.migrations._discovery import discover_plugin_migrations_and_models
from app.sep.migrations._orphan_heads import skip_unresolvable_heads
from app.sep.pom.config import pom_schema_translate_map
from app.core.settings_override.models import *
from app.sep.models import *
from app.sep.snippets.models import *

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

discover_plugin_migrations_and_models()

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = SQLModel.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    Note for POM: Alembic applies no ``schema_translate_map`` offline -- there is no
    connection to carry one -- so a generated script names ``pom_schema`` literally
    and has to be edited before it is run. Online mode is what ``make migrate`` uses.

    """
    url = sep_settings.DATABASE.URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version_sep",
        compare_type=compare_type,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table="alembic_version_sep",
        compare_type=compare_type,
    )
    skip_unresolvable_heads(context)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """In this scenario we need to create an Engine
    and associate a connection with the context.

    """

    config_section = config.get_section(config.config_ini_section, {})
    config_section["sqlalchemy.url"] = sep_settings.DATABASE.URL
    connectable = async_engine_from_config(
        config_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # POM's migrations name ``pom_schema`` symbolically, exactly as its models do, so
    # the connection that runs them has to translate it the way the application engine
    # does. Without this a POM migration creates a literal ``pom_schema`` schema on a
    # PostgreSQL bind and fails outright on SQLite.
    connectable = connectable.execution_options(
        schema_translate_map=pom_schema_translate_map(sep_settings.DATABASE)
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
