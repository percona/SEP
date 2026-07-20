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


class DatabaseOptions(BaseModel):
    """Define configuration options for a database connection.

    :param ENGINE: The database engine to use (e.g., SQLite, MySQL, PostgreSQL).
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

    @computed_field(repr=False)
    @property
    def URL(self) -> str:
        """Construct the database connection URL.

        :return: A string representing the connection URL based on the configuration.
        :rtype: str
        """
        host = self.HOST
        name = self.NAME
        if self.HOST is None or self.HOST == "":
            host = f"/{self.NAME}"
            name = None
        return str(
            AnyUrl.build(
                scheme=self.ENGINE,
                host=host,
                username=self.USER,
                password=self.PASSWORD.get_secret_value() if self.PASSWORD else None,
                port=self.PORT,
                path=name,
            ),
        )

    @property
    def pool_engine_kwargs(self) -> dict[str, int | float]:
        """Return only the explicitly-set pool options as ``create_engine`` kwargs.

        An unset field is omitted entirely so the engine keeps SQLAlchemy's own
        default, leaving standalone deployments byte-for-byte unchanged.

        :return: The set pool options keyed by their lowercase engine-kwarg names.
        """
        return {
            key: value
            for key, value in {
                "pool_size": self.POOL_SIZE,
                "max_overflow": self.MAX_OVERFLOW,
                "pool_timeout": self.POOL_TIMEOUT,
            }.items()
            if value is not None
        }
