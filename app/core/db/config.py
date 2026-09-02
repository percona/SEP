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

"""Define database settings."""

from urllib.parse import quote

from pydantic import (
    AnyUrl,
    BaseModel,
    computed_field,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    SecretStr,
)

from app.core.utils.fields import AsyncDatabaseEngine

#: The driver kwarg each async dialect uses for its connect timeout. asyncpg
#: takes ``timeout``; aiosqlite's ``timeout`` means lock wait, not connect, so
#: SQLite is absent.
_CONNECT_TIMEOUT_KEYS: dict[AsyncDatabaseEngine, str] = {
    AsyncDatabaseEngine.POSTGRESQL: "timeout",
}


class DatabaseOptions(BaseModel):
    """Define configuration options for a database connection.

    :param ENGINE: The database engine to use (e.g., SQLite, PostgreSQL).
        Defaults to SQLite.
    :param USER: The username for the database connection.
    :param PASSWORD: The password for the database connection.
    :param HOST: The hostname or IP address of the database server.
    :param PORT: The port number on which the database is running.
    :param NAME: The name of the database.
    :param POOL_SIZE: Maximum number of persistent pool connections. Unset keeps
        SQLAlchemy's default. Must be ``>= 1``; ``0`` requests an unbounded pool,
        a footgun under a shared connection cap.
    :param MAX_OVERFLOW: Connections allowed beyond ``POOL_SIZE``. Unset keeps
        SQLAlchemy's default. ``0`` disables overflow; ``-1`` (unlimited) is
        rejected.
    :param POOL_TIMEOUT: Seconds to wait for a free connection. Unset keeps
        SQLAlchemy's default. Must be ``> 0``.
    :param CONNECT_TIMEOUT: Seconds to wait for a TCP connect. Unset passes no
        ``connect_args``, leaving the driver's own default. Forwarded as
        ``timeout`` for asyncpg; omitted for SQLite, where that key means lock
        wait rather than connect. Must be ``> 0``.
    :param POOL_PRE_PING: Whether to test each pooled connection for liveness
        before handing it out. Defaults to ``True`` so a dead connection is
        discarded and replaced transparently. Unlike the sizing fields, this
        is a plain ``bool`` rather than ``bool | None`` because the point is
        to override SQLAlchemy's ``False`` default, not to fall back to it.
    """

    ENGINE: AsyncDatabaseEngine = AsyncDatabaseEngine.SQLITE
    USER: str | None = None
    PASSWORD: SecretStr | None = None
    HOST: str | None = None
    PORT: int | None = None
    NAME: str
    POOL_SIZE: PositiveInt | None = None
    MAX_OVERFLOW: NonNegativeInt | None = None
    POOL_TIMEOUT: PositiveFloat | None = None
    CONNECT_TIMEOUT: PositiveFloat | None = None
    POOL_PRE_PING: bool = True

    @computed_field(repr=False)
    @property
    def URL(self) -> str:
        """Construct the database connection URL.

        The credentials are percent-encoded first because ``AnyUrl.build`` escapes
        ``@`` and ``:`` but leaves ``/`` alone, so a ``/`` in either would end the
        authority and leave the port unparseable.

        :return: A string representing the connection URL based on the configuration.
        """
        host = self.HOST
        name = self.NAME
        if self.HOST is None or self.HOST == "":
            host = f"/{self.NAME}"
            name = None
        password = self.PASSWORD.get_secret_value() if self.PASSWORD else None
        return str(
            AnyUrl.build(
                scheme=self.ENGINE,
                host=host,
                username=None if self.USER is None else quote(self.USER, safe=""),
                password=None if password is None else quote(password, safe=""),
                port=self.PORT,
                path=name,
            ),
        )

    @property
    def pool_engine_kwargs(self) -> dict[str, int | float | bool]:
        """Return pool options as ``create_engine`` kwargs.

        ``pool_pre_ping`` is always emitted so the engine overrides SQLAlchemy's
        ``False`` default. Sizing fields are omitted when unset so the engine
        keeps SQLAlchemy's own defaults for those.

        :return: Pool options keyed by their lowercase engine-kwarg names.
        """
        return {
            "pool_pre_ping": self.POOL_PRE_PING,
            **{
                key: value
                for key, value in {
                    "pool_size": self.POOL_SIZE,
                    "max_overflow": self.MAX_OVERFLOW,
                    "pool_timeout": self.POOL_TIMEOUT,
                }.items()
                if value is not None
            },
        }

    @property
    def connect_engine_kwargs(self) -> dict[str, dict[str, float]]:
        """Return ``connect_args`` as a ``create_engine`` kwarg, or ``{}``.

        An unset ``CONNECT_TIMEOUT``, or an engine with no connect-timeout
        meaning (SQLite), yields ``{}`` so the caller can omit ``connect_args``
        from ``create_async_engine`` entirely — the same omit-when-empty
        contract as :attr:`pool_engine_kwargs`.

        :return: ``{"connect_args": {dialect_key: timeout}}`` or ``{}``.
        """
        if self.CONNECT_TIMEOUT is None:
            return {}
        key = _CONNECT_TIMEOUT_KEYS.get(self.ENGINE)
        if key is None:
            return {}
        return {"connect_args": {key: self.CONNECT_TIMEOUT}}
