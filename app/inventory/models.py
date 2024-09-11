"""Define models for the Inventory API."""

from pydantic import AliasChoices
from pydantic import BaseModel
from pydantic import Field

from app.core.fields import RequiredStr


class Node(BaseModel):
    """Represents a node in the inventory.

    Attributes
    ----------
    address : RequiredStr
        The network address of the node.
    name : RequiredStr
        The name of the node. This field supports multiple validation aliases:
        "node_name" and "name".
    node_id : RequiredStr
        The unique identifier of the node.
    type : RequiredStr
        The type of the node (e.g., remote, generic).

    """

    address: RequiredStr
    name: RequiredStr = Field(validation_alias=AliasChoices("node_name", "name"))
    node_id: RequiredStr
    type: RequiredStr


class Service(BaseModel):
    """Represents a service running on a node in the inventory.

    Attributes
    ----------
    node_id : RequiredStr
        The unique identifier of the node on which the service is running.
    service_id : RequiredStr
        The unique identifier of the service.
    name : RequiredStr
        The name of the service. This field supports multiple validation aliases:
        "service_name" and "name".
    type : RequiredStr
        The type of the service (e.g., mysql, postgresql).
    port : int
        The port number on which the service is running.
    database_name : str, optional
        The name of the database associated with the service, if any. Defaults to None.
    environment : str, optional
        The environment in which the service is running, if set. Defaults to None.

    """

    node_id: RequiredStr
    service_id: RequiredStr
    name: RequiredStr = Field(validation_alias=AliasChoices("service_name", "name"))
    type: RequiredStr
    port: int | None = None
    database_name: str | None = None
    environment: str | None = None


class InventoryItem(Node):
    """Represents an inventory item, which includes a node and its associated services.

    Attributes
    ----------
    services : list of Service, optional
        A list of services running on the node.

    """

    services: list[Service] = []
