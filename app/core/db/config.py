"""Define database settings."""

from enum import StrEnum

from pydantic import AnyUrl, BaseModel, computed_field, field_validator


class DBEngine(StrEnum):
    """Enum representing supported database engines.

    :cvar SQLITE: SQLite engine string, using the `aiosqlite` driver.
    :vartype SQLITE: str
    :cvar MYSQL: MySQL engine string, using the `aiomysql` driver.
    :vartype MYSQL: str
    :cvar POSTGRESQL: PostgreSQL engine string, using the `asyncpg` driver.
    :vartype POSTGRESQL: str
    """

    SQLITE = "sqlite+aiosqlite"
    MYSQL = "mysql+aiomysql"
    POSTGRESQL = "postgresql+asyncpg"


class DatabaseOptions(BaseModel):
    """Configuration options for a database connection.

    :param ENGINE: The database engine to use (e.g., SQLite, MySQL, PostgreSQL).
        Defaults to SQLite.
    :type ENGINE: DBEngine
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

    ENGINE: DBEngine = DBEngine.SQLITE
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

    @field_validator("ENGINE", mode="before")
    @classmethod
    def validate_engine(cls, v: DBEngine | str) -> DBEngine:
        """Validate the database engine.

        Convert a string to a `DBEngine` enum if necessary, raising an error
        if the value is not valid.

        :param v: The database engine value to validate.
        :type v: DBEngine | str
        :return: The validated and converted `DBEngine` enum value.
        :rtype: DBEngine
        :raises ValueError: If the provided value is not a valid database engine.
        """
        if isinstance(v, DBEngine):
            return v
        try:
            return DBEngine[v.upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid engine: '{v}'") from exc
