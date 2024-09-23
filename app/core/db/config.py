"""Define database settings"""

from enum import StrEnum

from pydantic import AnyUrl
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import field_validator


class DBEngine(StrEnum):
    """Enum representing supported database engines.

    Attributes
    ----------
    SQLITE : str
        SQLite engine string, using the `aiosqlite` driver.
    MYSQL : str
        MySQL engine string, using the `aiomysql` driver.
    POSTGRESQL : str
        PostgreSQL engine string, using the `asyncpg` driver.

    """

    SQLITE = "sqlite+aiosqlite"
    MYSQL = "mysql+aiomysql"
    POSTGRESQL = "postgresql+asyncpg"


class DatabaseOptions(BaseModel):
    """Configuration options for a database connection.

    Attributes
    ----------
    ENGINE : DBEngine
        The database engine to use (e.g., SQLite, MySQL, PostgreSQL).
        Defaults to SQLite.
    USER : str or None
        The username for the database connection.
    PASSWORD : str or None
        The password for the database connection.
    HOST : str or None
        The hostname or IP address of the database server.
    PORT : int or None
        The port number on which the database is running.
    NAME : str
        The name of the database.
    URL

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

        Returns
        -------
        str
            A string representing the connection URL based on the configuration.

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

        Parameters
        ----------
        v : DBEngine or str
            The database engine value to validate.

        Returns
        -------
        DBEngine
            The validated and converted `DBEngine` enum value.

        Raises
        ------
        ValueError
            If the provided value is not a valid database engine.

        """
        if isinstance(v, DBEngine):
            return v
        try:
            return DBEngine[v.upper()]
        except KeyError as exc:
            raise ValueError(f"Invalid engine: '{v}'") from exc
