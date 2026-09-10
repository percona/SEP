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

#: The dialects this class emits pool sizing for. SQLite is excluded whole
#: rather than per-backing, which is a choice worth stating: only an in-memory
#: database gets a ``StaticPool``, which raises ``TypeError`` when handed these
#: kwargs, while a file-backed one gets an ``AsyncAdaptedQueuePool`` that would
#: accept them. Splitting the carve-out that way would make the same setting
#: work on one SQLite database and crash another, and no SQLite database has a
#: server-side connection cap to budget against in the first place — so a
#: sizing value configured against SQLite is ignored rather than forwarded.
_POOL_SIZED_ENGINES: frozenset[AsyncDatabaseEngine] = frozenset(
    {AsyncDatabaseEngine.POSTGRESQL},
)


class DatabaseOptions(BaseModel):
    """Define configuration options for a database connection.

    The sizing defaults are deliberately tighter than SQLAlchemy's own. A
    shipped deployment runs five long-running programs building at least eight
    engines between them, five of which come from this class: four in the three
    API processes, and one in the Celery worker that the prefork pool replicates
    per child, so the worker's share scales with its concurrency rather than
    being a fixed count. At SQLAlchemy's ``5 + 10`` the four API-side engines
    alone reach 60 against a stock PostgreSQL ``max_connections`` of 100 and the
    worker's children take the rest, at which point the server refuses new
    connections outright. ``3 + 2`` caps every engine this class feeds at five
    concurrent connections, a third of what it allowed before, which is what
    bounds the per-child cost too. A deployment that needs more sets these
    fields, which is what they exist for.

    :param ENGINE: The database engine to use (e.g., SQLite, PostgreSQL).
        Defaults to SQLite.
    :param USER: The username for the database connection.
    :param PASSWORD: The password for the database connection.
    :param HOST: The hostname or IP address of the database server.
    :param PORT: The port number on which the database is running.
    :param NAME: The name of the database.
    :param POOL_SIZE: Maximum number of persistent pool connections. Defaults to
        ``3``. Must be ``>= 1``; ``0`` requests an unbounded pool, a footgun
        under a shared connection cap.
    :param MAX_OVERFLOW: Connections allowed beyond ``POOL_SIZE``. Defaults to
        ``2``, capping each engine at five concurrent connections. ``0``
        disables overflow; ``-1`` (unlimited) is rejected.
    :param POOL_TIMEOUT: Seconds to wait for a free connection. Defaults to
        ``10.0``, so a saturated pool refuses the request rather than holding
        it. Must be ``> 0``.
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
    POOL_SIZE: PositiveInt | None = 3
    MAX_OVERFLOW: NonNegativeInt | None = 2
    POOL_TIMEOUT: PositiveFloat | None = 10.0
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
        ``False`` default. The sizing fields are emitted only for a dialect in
        :data:`_POOL_SIZED_ENGINES` — the same per-dialect carve-out
        :attr:`connect_engine_kwargs` applies, and it discards a value
        configured against SQLite rather than forwarding it — and then only when
        set, so an explicit ``None`` still falls back to SQLAlchemy's own
        default for that field.

        :return: Pool options keyed by their lowercase engine-kwarg names.
        """
        if self.ENGINE not in _POOL_SIZED_ENGINES:
            return {"pool_pre_ping": self.POOL_PRE_PING}
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
