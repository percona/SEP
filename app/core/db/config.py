"""Define database settings."""

from pydantic import AnyUrl, BaseModel, computed_field

from app.core.fields import AsyncDatabaseEngine


class DatabaseOptions(BaseModel):
    """Configuration options for a database connection.

    :param ENGINE: The database engine to use (e.g., SQLite, MySQL, PostgreSQL).
        Defaults to SQLite.
    :type ENGINE: AsyncDatabaseEngine
    :param USER: The username for the database connection.
    :type USER: str | None
    :param PASSWORD: The password for the database connection.
    :type PASSWORD: str | None
    :param HOST: The hostname or IP address of the database server.
    :type HOST: str | None
    :param PORT: The port number on which the database is running.
    :type PORT: int | None
    :param NAME: The name of the database.
    :type NAME: str
    """

    ENGINE: AsyncDatabaseEngine = AsyncDatabaseEngine.SQLITE
    USER: str | None = None
    PASSWORD: str | None = None
    HOST: str | None = None
    PORT: int | None = None
    NAME: str

    @computed_field
    @property
    def URL(self) -> str:
        """Construct the database connection URL.

        :return: A string representing the connection URL based on the configuration.
        :rtype: str
        """
        host = self.HOST
        name = self.NAME
        if self.HOST is None:
            host = f"/{self.NAME}"
            name = None
        return str(
            AnyUrl.build(
                scheme=self.ENGINE,
                host=host,
                username=self.USER,
                password=self.PASSWORD,
                port=self.PORT,
                path=name,
            ),
        )
