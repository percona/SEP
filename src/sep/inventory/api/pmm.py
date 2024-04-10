"""
PMM remote inventory
"""

from collections import (
    namedtuple,
    OrderedDict,
)
import json
import netrc
import ssl
import urllib.parse
import urllib.request


def to_dict(self):
    """

    :param self:
    :return:
    """
    if "services" in self._fields:
        current_data = self._asdict()
        current_data["services"] = []
        for svc in self.services:
            current_data["services"].append(svc.to_dict())
        self = self._make(current_data.values())
    return self._asdict()


def to_json(self):
    """

    :param self:
    :return:
    """
    return json.dumps(self.to_dict())


Node = namedtuple("Node", ["id", "name", "type", "services"])
Node.to_dict = to_dict
Node.to_json = to_json

Service = namedtuple("Service", ["cluster", "environment", "id", "name", "node_id", "type"])
Service.to_dict = to_dict


class InventorySource:
    """PMM inventory source"""

    __storage = {}

    def __init__(self, uri: str, verify_tls: bool, **kwargs):
        """Initialise the source

        :param uri:
        :param verify_tls:
        :param kwargs:
        :return:
        """
        self.base_uri = uri
        self.uri = urllib.parse.urlparse(self.base_uri)

        if not verify_tls:
            # noinspection PyProtectedMember
            tls_context = ssl._create_unverified_context()  # noqa: S323 # nosec B323
        else:
            tls_context = ssl.create_default_context()
        tls_handler = urllib.request.HTTPSHandler(context=tls_context)
        handlers = [tls_handler]

        if kwargs.get("use_cookies", []) and isinstance(kwargs["use_cookies"], list):
            raise NotImplementedError("Cookie access is not currently supported")
        else:
            if "auth" not in kwargs:
                credentials = netrc.netrc()  # TODO: add support for configurable paths
                auth = credentials.authenticators(self.uri.hostname)
            else:
                auth = kwargs["auth"]

            if not auth or len(auth) != 3:
                raise UserWarning("No auth found")

            password_mgr = urllib.request.HTTPPasswordMgrWithPriorAuth()
            password_mgr.add_password(
                realm=None, uri=self.base_uri, user=auth[0], passwd=auth[2], is_authenticated=True
            )
            handlers.append(urllib.request.HTTPBasicAuthHandler(password_mgr))

        opener = urllib.request.build_opener(*handlers)
        urllib.request.install_opener(opener)
        self._headers = {"content-type": "application/json", "accept": "application/json"}

    def request(self, uri: str, payload: bytes = b"", timeout: int = 60):
        """Make a request"""
        args = {} if not payload else dict(data=payload)
        if timeout:
            args["timeout"] = timeout
        if not uri.startswith(("https:", "http:")):
            raise ValueError(f"the URI does not appear to be HTTP: {uri}")
        req = urllib.request.Request(uri, payload, self._headers, method="GET" if not payload else "POST")  # noqa: S310
        with urllib.request.urlopen(req, **args) as resp:  # noqa: S310 # nosec B310
            data = resp.read().decode("utf-8")
            return dict(raw=data, json=json.loads(data))

    @property
    def nodes(self) -> dict[Node]:
        """Lookup all nodes"""
        if "nodes" not in self.__storage:
            req = self.request(f"{self.base_uri}/v1/inventory/Nodes/List", payload=b"{}")
            nodes = {}
            for node_type, data in req.get("json", {}).items():
                # TODO: Lookup extra data for the node
                for node in data:
                    nodes[node["node_id"]] = Node(
                        id=node["node_id"],
                        name=node["node_name"],
                        services=[v for _, v in self.services.items() if v.node_id == node["node_id"]],
                        type=node_type,
                    )
            self.__storage["nodes"] = nodes
        return self.__storage["nodes"]

    @property
    def organisations(self) -> list[OrderedDict]:
        """
        Lookup the organisations

        :return:
        """
        if "orgs" not in self.__storage:
            self.__storage["orgs"] = OrderedDict()
            resp = self.request(f"{self.base_uri}/graph/api/orgs", payload=b"")
            for org in resp.get("json", []):
                if "name" not in org:
                    continue
                self.__storage["orgs"][org["name"]] = org
        return self.__storage["orgs"]

    @property
    def services(self) -> dict[Service]:
        """Lookup all services"""
        if "services" not in self.__storage:
            req = self.request(f"{self.base_uri}/v1/inventory/Services/List", payload=b"{}")
            services = {}
            for service_type, data in req.get("json", {}).items():
                for service in data:
                    services[service["service_id"]] = Service(
                        cluster=service.get("cluster"),
                        id=service["service_id"],
                        name=service["service_name"],
                        node_id=service["node_id"],
                        environment=service.get("environment"),
                        type=service_type,
                    )
            self.__storage["services"] = services
        return self.__storage["services"]
