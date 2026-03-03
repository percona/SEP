# Copyright 2025 Percona LLC
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

from pydantic import AnyUrl, BaseModel, computed_field, SecretStr

from app.core.utils.fields import AsyncDatabaseEngine


class DatabaseOptions(BaseModel):
    """Configuration options for a database connection.

    :param ENGINE: The database engine to use (e.g., SQLite, MySQL, PostgreSQL).
        Defaults to SQLite.
    :type ENGINE: AsyncDatabaseEngine
    :param USER: The username for the database connection.
    :type USER: str | None
    :param PASSWORD: The password for the database connection.
    :type PASSWORD: SecretStr | None
    :param HOST: The hostname or IP address of the database server.
    :type HOST: str | None
    :param PORT: The port number on which the database is running.
    :type PORT: int | None
    :param NAME: The name of the database.
    :type NAME: str
    """

    ENGINE: AsyncDatabaseEngine = AsyncDatabaseEngine.SQLITE
    USER: str | None = None
    PASSWORD: SecretStr | None = None
    HOST: str | None = None
    PORT: int | None = None
    NAME: str

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
