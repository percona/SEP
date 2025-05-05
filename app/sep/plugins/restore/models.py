from app.core.models import BaseCaseInsensitiveModel
from app.core.utils.fields import RequiredStr

class RestoreConfigAll(BaseCaseInsensitiveModel):
    pass

class RestoreConfigServer(BaseCaseInsensitiveModel):
    """Represent an individual server configuration.

    :param alias: A unique alias for the server.
    :type alias: RequiredStr
    :param restore_type: The type of the restore.
    :type restore_type: RestoreType
    :param host: The hostname or address of the server.
    :type host: RequiredStr
    :param port: The port number used to connect to the host.
    :type port: int | None
    :param upload: A unique list of upload providers to use for the restore, if any.
    :type upload: UniqueList[UploadProvider] | None
    :param dir_encrypt_config: Specific configuration for the restore encryption.
    :type dir_encrypt_config: DirEncryptConfig | None
    """

    alias: RequiredStr
    restore_type: str
    host: RequiredStr
    port: int | None
    upload: list[str] | None = None

class RestoreConfig(BaseCaseInsensitiveModel):
    """Represent the overall restore configuration.

    :param all_servers: General settings for the restore.
    :type all_servers: RestoreConfigAll
    :param server_list: A list of restore configuration for each server.
    :type server_list: list[RestoreConfigServer]
    """

    all_servers: RestoreConfigAll
    server_list: list[RestoreConfigServer]
