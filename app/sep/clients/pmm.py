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

"""PMM API client for interacting with the PMM inventory system."""

import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from async_lru import _LRUCacheWrapper, alru_cache
from pydantic import ConfigDict, SecretStr, ValidationError

from app.core.requests import RemoteAPI
from app.core.utils.dict import remove_falsy_values_from_dict
from app.core.utils.fields import NonEmptyStr
from app.inventory.models import SourceEnum
from app.sep.inventory import Node, Service

logger = logging.getLogger(__name__)


class PMMService(Service):
    """Represent a PMM-specific inventory service.

    This class extends the base `Service` model to include PMM-specific attributes
    such as the node string identifier (external_id).

    :param environment: The environment in which the service is running (e.g.,
        "production", "staging"). Defaults to None.
    :type environment: str | None
    :param cluster: The cluster in which the service is running. Defaults to None.
    :type cluster: str | None
    :param replication_set: The replication set in which the service is running. Defaults to None.
    :type replication_set: str | None
    :param custom_labels: Custom labels associated with the service. Defaults to None.
    :type custom_labels: dict[str, Any] | None
    :param external_id: The external identifier for the service, aliased as
        "service_id". Defaults to None.
    :type external_id: NonEmptyStr | EmptyStrToNone
    :param name: The name of the service, aliased as "service_name".
    :type name: NonEmptyStr
    :param port: The port number on which the service is running, aliased as
        "service_port". Defaults to None.
    :type port: int | EmptyStrToNone
    :param type: The type of the service (e.g., "service_type"), aliased as
        "service_type". Defaults to "generic".
    :type type: NonEmptyStr
    :param node_id: The identifier of the node to which the service is associated.
    :type node_id: str
    """

    node_id: str


class PMMRemoteAPI(RemoteAPI):
    """Handle remote API interactions specific to PMM.

    Provides methods to interact with the PMM inventory system, including fetching nodes
    and services, and managing service associations.

    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePathField | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePathField | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePathField | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    :param api_key: The API key for authentication. Defaults to None.
    :type api_key: SecretStr | None
    :param error_detail_key: The key to expect errors details to be. Defaults to
        "message".
    :type error_detail_key: NonEmptyStr
    :param error_code_key: The key to expect error codes to be, or None if no error
        code is expected. Defaults to "code".
    :type error_code_key: NonEmptyStr | None
    :param default_to_v3: Whether to default to PMM v3 API endpoints if the API version
        cannot be determined. Defaults to True.
    :type default_to_v3: bool
    """

    model_config = ConfigDict(ignored_types=(_LRUCacheWrapper,))
    api_key: SecretStr
    error_detail_key: NonEmptyStr = "message"
    error_code_key: NonEmptyStr | None = "code"
    default_to_v3: bool = True

    @property
    def headers(self) -> dict[str, str]:
        """Return the headers to be used in PMM requests.

        Includes content type, accept headers, and authorization with the API key.

        :return: A dictionary containing the headers for PMM API requests.
        :rtype: dict[str, str]
        """
        return {
            **super().headers,
            "Authorization": f"Bearer {self.api_key.get_secret_value()}",
        }

    @alru_cache(ttl=600)
    async def is_older_than_v3(self) -> bool:
        """Check if the PMM version is older than 3.

        This method retrieves the PMM version and checks if it is older than 3.0.0.

        :return: True if the PMM version is older than 3, False otherwise.
        :rtype: bool
        """
        v3_major = 3
        try:
            version = await self.get_version()
        except (TypeError, KeyError):
            self.logger.exception(
                "Failed to retrieve PMM version, defaulting to %s",
                "v3" if self.default_to_v3 else "v2",
            )
            return not self.default_to_v3

        try:
            is_older = int(version.split(".")[0]) < v3_major
        except (AttributeError, ValueError):
            self.logger.exception(
                "Failed to parse PMM version, defaulting to %s: %s",
                "v3" if self.default_to_v3 else "v2",
                version,
            )
            return not self.default_to_v3

        if is_older:
            self.logger.warning(
                "Deprecation Warning: Support for PMM version < 3.0.0 is deprecated and will be removed in a future version (version found is %s).",
                version,
            )
        return is_older

    async def get_version(self) -> str:
        """Retrieve the PMM version.

        :return: The version of the PMM instance.
        :rtype: str
        """
        version_data = await self.get("/v1/version")
        return version_data["version"]

    async def get_node(
        self,
        node_id: str,
        *,
        skip_failed_services: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> Node | None:
        """Retrieve a PMM node by its external ID.

        Send a request to the PMM API to fetch a node's details by its external ID.

        :param node_id: The external identifier of the node to retrieve.
        :type node_id: str
        :param skip_failed_services: Whether to skip services that fail validation.
            Defaults to True.
        :type skip_failed_services: bool
        :param filter_: Optional callable that takes a node or service dict and returns
            True if the item should be included, False if it should be filtered out.
            Used to filter the node and, when loading services, each service.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: The retrieved node instance, or None if filtered out.
        :rtype: Node | None
        """
        if await self.is_older_than_v3():
            node_data = await self.post(
                "/v1/inventory/Nodes/Get",
                json={"node_id": node_id},
            )
        else:
            node_data = await self.get(
                f"/v1/inventory/nodes/{node_id}",
            )
        node_type, node = next(iter(node_data.items()))
        if filter_ is not None and not filter_(node):
            self.logger.debug(
                "Skipping node %s due to filter",
                node_id,
            )
            return None
        node |= {
            "source": SourceEnum.PMM,
            "type": node_type,
            "services": await self.get_services(
                node_id=node_id,
                skip_failed=skip_failed_services,
                filter_=filter_,
            ),
        }
        return Node.model_validate(node)

    async def get_service(
        self,
        service_id: str,
        *,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> PMMService | None:
        """Retrieve a PMM service by its ID.

        Send a request to the PMM API to fetch a service's details by its ID.

        :param service_id: The identifier of the service to retrieve.
        :type service_id: str
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: The retrieved service instance, or None if filtered out.
        :rtype: PMMService | None
        """
        if await self.is_older_than_v3():
            service_data = await self.post(
                "/v1/inventory/Services/Get",
                json={"service_id": service_id},
            )
        else:
            service_data = await self.get(
                f"/v1/inventory/services/{service_id}",
            )
        service_type, service = next(iter(service_data.items()))
        if filter_ is not None and not filter_(service):
            self.logger.debug(
                "Skipping service %s due to filter",
                service_id,
            )
            return None
        service["type"] = service_type
        return PMMService.model_validate(service)

    async def get_services(
        self,
        node_id: str = "",
        service_type: str = "",
        external_group: str = "",
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[PMMService]:
        """Fetch services from the PMM API.

        Retrieve a list of services filtered by node ID, service type, and external
        group.

        :param node_id: The ID of the node to filter services by. Defaults to an empty
            string, meaning the field won't be used as a filter.
        :type node_id: str
        :param service_type: The type of services to filter by. Defaults to an empty
            string, meaning the field won't be used as a filter.
        :type service_type: str
        :param external_group: The external group to filter services by. Defaults to an
            empty string, meaning the field won't be used as a filter.
        :type external_group: str
        :param skip_failed: Whether to skip services that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A list of PMMService instances retrieved from the API.
        :rtype: list[PMMService]
        :raises ValidationError: If a service fails validation and `skip_failed` is
            False.
        """
        params = {
            "node_id": node_id,
            "service_type": service_type,
            "external_group": external_group,
        }
        params = remove_falsy_values_from_dict(params)
        if await self.is_older_than_v3():
            services_data = await self.post("/v1/inventory/Services/List", json=params)
        else:
            services_data = await self.get("/v1/inventory/services", params=params)

        services = []
        for services_type, service_list in services_data.items():
            for service in service_list:
                if filter_ is not None and not filter_(service):
                    self.logger.debug(
                        "Skipping service %s due to filter",
                        service.get("service_id"),
                    )
                    continue
                try:
                    services.append(
                        PMMService.model_validate({"type": services_type, **service})
                    )
                except ValidationError:
                    if skip_failed:
                        self.logger.exception(
                            "Validation Error: Skipping service of type %s with data %s",
                            services_type,
                            service,
                        )
                    else:
                        raise
        return services

    async def get_services_by_node_external_id(
        self,
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> defaultdict[NonEmptyStr, list[PMMService]]:
        """Fetch and group services by node ID from the PMM API.

        Retrieve all services and organize them into a defaultdict where each key is a
        node ID and each value is a list of associated services.

        :param skip_failed: Whether to skip services that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a service dict and returns True if
            the service should be included, False if it should be filtered out.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A defaultdict mapping node IDs to lists of PMMService instances.
        :rtype: defaultdict[NonEmptyStr, list[PMMService]]
        """
        services_by_node_id = defaultdict(list)
        for service in await self.get_services(
            skip_failed=skip_failed, filter_=filter_
        ):
            services_by_node_id[service.node_id].append(service)
        return services_by_node_id

    async def get_nodes(
        self,
        node_type: str = "",
        *,
        skip_failed: bool = True,
        filter_: Callable[[dict[str, Any]], bool] | None = None,
    ) -> list[Node]:
        """Fetch nodes from the PMM API.

        Retrieve a list of nodes filtered by node type and associate them with their
        services.

        :param node_type: The type of nodes to retrieve (e.g., "generic"). Defaults to
            an empty string, meaning the field won't be used as a filter.
        :type node_type: str
        :param skip_failed: Whether to skip nodes that fail validation. Defaults to
            True.
        :type skip_failed: bool
        :param filter_: Optional callable that takes a node or service dict and returns
            True if the item should be included, False if it should be filtered out.
            Used to filter nodes and, when loading services, each service.
            Defaults to None.
        :type filter_: Callable[[dict[str, Any]], bool] | None
        :return: A list of Node instances retrieved from the API.
        :rtype: list[Node]
        :raises ValidationError: If a node fails validation and `skip_failed` is False.
        """
        services_by_node_id = await self.get_services_by_node_external_id(
            skip_failed=skip_failed, filter_=filter_
        )
        params = remove_falsy_values_from_dict({"node_type": node_type})
        if await self.is_older_than_v3():
            nodes_data = await self.post(
                "/v1/inventory/Nodes/List",
                json=params,
            )
        else:
            nodes_data = await self.get("/v1/inventory/nodes", params=params)

        nodes = []
        for nodes_type, node_list in nodes_data.items():
            for node in node_list:
                if filter_ is not None and not filter_(node):
                    self.logger.debug(
                        "Skipping node %s due to filter",
                        node.get("node_id"),
                    )
                    continue
                try:
                    nodes.append(
                        Node(
                            **node,
                            source=SourceEnum.PMM,
                            type=nodes_type,
                            services=services_by_node_id[node["node_id"]],
                        )
                    )
                except ValidationError:
                    if not skip_failed:
                        raise
                    self.logger.exception(
                        "Failed to validate node of type %s with data: %s",
                        nodes_type,
                        node,
                    )
        return nodes
