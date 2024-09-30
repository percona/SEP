"""Define models for the Inventory plugin."""

from pydantic import BaseModel
from pydantic import Field

from app.core.fields import EmptyStrToNone
from app.core.fields import RequiredStr


class CreateNodeRequest(BaseModel):
    """Represent the request schema for creating a new node.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    name : RequiredStr
        The name of the node.
    external_id : RequiredStr or EmptyStrToNone, optional
        An external identifier for the node. Defaults to None.
    source : RequiredStr or EmptyStrToNone, optional
        The source of the node information. Defaults to None.
    node_type : RequiredStr, optional
        The type of the node (e.g., "generic", "remote"). Serialized as "type".
        Defaults to "generic".

    """

    address: RequiredStr
    name: RequiredStr
    external_id: RequiredStr | EmptyStrToNone = None
    source: RequiredStr | EmptyStrToNone = None
    node_type: RequiredStr = Field(default="generic", serialization_alias="type")


class CreateServiceRequest(BaseModel):
    """Represent the request schema for creating a new service.

    Attributes
    ----------
    name : RequiredStr
        The name of the service.
    service_type : RequiredStr, optional
        The type of the service (e.g., "mysql", "postgresql"). Serialized as "type".
    external_id : RequiredStr or EmptyStrToNone, optional
        An external identifier for the service. Defaults to None.
    port : int or EmptyStrToNone, optional
        The port number on which the service is running. Defaults to None.
    environment : str or None, optional
        The environment in which the service is running (e.g., "production", "staging").
        Defaults to None.

    """

    name: RequiredStr
    service_type: RequiredStr = Field(serialization_alias="type")
    external_id: RequiredStr | EmptyStrToNone = None
    port: int | EmptyStrToNone = None
    environment: str | None = None


class CreateSchemaRequest(BaseModel):
    """Represent the request schema for creating a new database schema.

    Attributes
    ----------
    name : RequiredStr
        The name of the schema.

    """

    name: RequiredStr


class CreateTableRequest(BaseModel):
    """Represent the request schema for creating a new table within a schema.

    Attributes
    ----------
    name : RequiredStr
        The name of the table.
    create : RequiredStr
        The SQL statement used to create the table.

    """

    name: RequiredStr
    create: RequiredStr
