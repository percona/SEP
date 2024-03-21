"""
SEP: Services Enablement Platform

Example config (JSON):
{
    "authz": {
        "backend": {
            "application_name": "<app-name>",
            "certificate": "<single-line-cert-as-base64-encoded-string> | <env-var> | <file-path>",
            "client_id": "<client-id>",
            "client_secret": "<client-secret>",
            "endpoint": "<authz-endpoint>",
            "org_name": "<org-name>"
        },
        "config": {
            "backend_cookie": "<authz-cookie-name>",
            "redirect_uri": "<scheme>://<host>:<port>/api/signin",
            "secret_type": "inline | env | filesystem",
            "session_cookie": "<sesion-cookie-name>"
        }
    },
    "handlers": [
        ["/some-remote-app/", "sep.handlers.RemoteCallHandler", {"uri": "http://127.0.0.1:8282"}, ""],
        ["/some-app-with-config/(?P<route>jobs|deployments)?$", "someapp.Handler",
            {"host": "127.0.0.1", "secure": false, "timeout": 10, "verify": false, "cert": []}, "someapp"],
    ],
    "modules": [],
    "port": <port>
}
"""

from argparse import FileType
import asyncio
from concurrent.futures import ProcessPoolExecutor
import importlib
from io import BytesIO
import json
import logging
import mimetypes
from os import (
    environ,
    getpid,
    path,
)
import pathlib
from secrets import token_bytes
from typing import (
    Callable,
    Optional,
    TypeVar,
    Union,
)

from casdoor import (
    AsyncCasdoorSDK,
    CasdoorSDK,
)
from tornado.log import app_log
from tornado.options import (
    define,
    _Option,
    options,
    parse_command_line,
    parse_config_file,
)
from tornado.web import (
    Application,
    StaticFileHandler,
)
from tornado.util import ObjectDict
import uvicorn
import yaml

from .audit import auditor_app as audit_app
from .authz import AuthZHandler
from .authz.casdoor import AuthzConfig
from .core import (
    DummyHandler,
    HomepageHandler,
    RemoteCallHandler,
)
from .inventory.api import app as inventory_app
from .inventory.router import get_default_router as inventory_router
from .tasks.api import app as tasks_app
from .tasks.nomad import NomadRemoteCallHandler
from .tasks.router import get_default_router as tasks_router

__all__ = []
__version__ = "0.0.1"

DEFAULTS = {
    "handlers": [],
    "modules": {},
    "port": 8181,
    "server_name": r"^((127\.([0-9]{1,3}\.){2}[0-9]{1,3})|localhost)$",
    "templates": {
        "dirs": [
            "#resolve#../../../templates",
            "#appdir....templates",
        ]
    },
}
HANDLER_DEFINITION_LENGTH = 4
HANDLER_DEFINITION_OPERATOR = "="
HANDLER_DEFINITION_REMOVE_AFTER = 3

define("authz", default={}, help="AuthZ configuration", type=dict)
define("handlers", default=[], help="Handler configuration", type=list)
define("modules", default={}, help="Module configuration", type=dict)
define("port", default=8181, help="Start of port range", type=int)
define("sep", default={"serve_traceback": True}, help="SEP application configuration", type=dict)
define("templates", default=DEFAULTS["templates"], help="Template configuration", type=dict)

Model = TypeVar("Model", bound="BaseModel")


class Config(ObjectDict):
    """
    Service Configuration
    """

    def __init__(self, data: dict, populate_defaults: bool = True):
        super().__init__(data)
        for k, v in data.copy().items():
            if isinstance(v, _Option):
                v = v.value()
            if callable(v):
                app_log.warning("%s is callable, ignoring", k)
                continue
            if isinstance(v, dict):
                setattr(self, k, Config(v, populate_defaults=False))
        if not populate_defaults:
            return
        for k, v in DEFAULTS.items():
            if not hasattr(self, k):
                setattr(self, k, v)
            elif k == "templates":
                self.templates.update(dirs=data["templates"].get("dirs", []) + v["dirs"])

    def get_handler_config(self) -> list:
        """Generate the config to set the app handlers

        :return: handlers for use with tornado.web.Application
        :rtype: list
        """
        if not hasattr(self, "handlers") or not isinstance(self.handlers, list):
            return []
        loaded_handlers = []
        for i, handler in enumerate(self.handlers):
            # TODO: We could allow variable length here, as the third item could be empty,
            #       this can be decided later on though as explicit could be better than
            #       implicit here anyway.
            if HANDLER_DEFINITION_OPERATOR != "=":
                raise NotImplementedError("Handler definitions are currently fixed-length lists")
            if not isinstance(handler, list) or len(handler) != HANDLER_DEFINITION_LENGTH:
                app_log.warning("Deleting handler due to incompatibility: %s", handler)
                continue
            try:
                if handler[1] not in ["RemoteCallHandler", "sep.RemoteCallHandler"]:
                    importlib.import_module(handler[1] if not handler[3] else handler[3])
            except ModuleNotFoundError:
                continue
            if HANDLER_DEFINITION_REMOVE_AFTER:
                self.handlers[i] = self.handlers[i][0:HANDLER_DEFINITION_REMOVE_AFTER]
            loaded_handlers.append(self.handlers[i])
            app_log.debug("Handler %s loaded", handler[1])

        # TODO: Built-in rules, here temporarily
        # With a registry, which in its simplest form could just be "modules" in the JSON config,
        # we could look up what should be enabled and go off to each to retrieve its handlers. This would
        # allow the app/handler/registry to be the source of the configuration. Perhaps this could even remove
        # the need to populate the handlers and instead get used to configure an intelligent router
        loaded_handlers.append([r"^/$", HomepageHandler, {}])
        loaded_handlers.append([r"^/api/(?P<route>signin|signout)$", AuthZHandler, {}])

        # Static file handler
        source_dir = path.abspath(path.join(__file__, "..", "..", ".."))
        if "static_path" in self.sep and self.sep.static_path is not None:
            static_path = pathlib.Path(self.sep.static_path)
            if not static_path.exists():
                raise asyncio.exceptions.CancelledError(f"Cannot find static_path {static_path}")
        else:
            static_path = path.abspath(path.join(source_dir, "static"))
        loaded_handlers.append([r"^/static/(.*)", StaticFileHandler, {"path": static_path}])

        # Built-in routers
        for handler in inventory_router(cfg=self.modules, handlers_only=True):
            loaded_handlers.append(handler)
        for handler in tasks_router(cfg=self.modules, handlers_only=True):
            loaded_handlers.append(handler)
        return loaded_handlers

    @staticmethod
    def load(config: Union[str, BytesIO, FileType, _Option], mimetype: Optional[str | bytes] = None) -> "Config":
        """Generate a Config instance

        :param config: the configuration file in JSON, or YAML format
        :type config: str, io.BytesIO, argparse.FileType, or tornado.options._Option
        :param mimetype: optionally set the mimetype to avoid guessing from the filename
        :type mimetype: str, bytes
        :return: the configuration object
        :rtype: Config (ObjectDict)
        """
        app_log.info("Loading config from %s", config)

        if isinstance(config, _Option):
            config = config.value()
        if isinstance(config, str):
            config = FileType(mode="rb")(config)
        if not mimetype:
            path = pathlib.Path(config.name)
            mimetypes.init(mimetypes.knownfiles + ["data/mime.types"])  # TODO: check path resolution
            mimetype = mimetypes.guess_type(path.absolute())

        match mimetype[0]:
            case "text/x-python":
                parse_config_file(config.name)
                config_data = {k.replace("-", "_"): v.value() for k, v in options.__dict__["_options"].items()}
            case "application/json":
                parse_command_line()
                config_data = Config._load_json(config)
            case "text/yaml":
                parse_command_line()
                config_data = Config._load_yaml(config)
            case _:
                raise ValueError(f"unknown mimetype {mimetype[0]} for config file {config.name}")

        # Validate
        Config._validate(config_data)

        # Process SEP
        if "serve_traceback" not in config_data["sep"]:
            config_data["sep"]["serve_traceback"] = True

        # Process authz
        sdk_config = config_data["authz"]["backend"].copy()
        match config_data["authz"]["config"]["secret_type"]:
            case "env":
                for k, v in config_data["authz"]["backend"].items():
                    sdk_config[k] = environ.get(v)
            case "filesystem":
                for k, v in config_data["authz"]["backend"].items():
                    with open(v, "rb") as source:
                        sdk_config[k] = source.read().strip()
            case _:
                # Inline expected as the default, nothing to set except to extract the cert
                import base64  # pylint: disable=import-outside-toplevel

                sdk_config["certificate"] = base64.b64decode(sdk_config["certificate"]).decode()

        config_data["authz"] = AuthzConfig(
            CASDOOR_COOKIE=config_data["authz"]["config"]["backend_cookie"],
            CASDOOR_SDK=AsyncCasdoorSDK(**sdk_config),
            CASDOOR_SDK_SYNC=CasdoorSDK(**sdk_config),
            REDIRECT_URI=config_data["authz"]["config"]["redirect_uri"],
            SECRET_KEY=token_bytes(24),  # TODO: read the key from a store to allow for multiple processes
            SESSION_COOKIE=config_data["authz"]["config"]["session_cookie"],
        )
        return Config(config_data)

    @staticmethod
    def _load_json(config: Union[BytesIO, FileType]) -> dict:
        """Load a JSON config

        :param config: the configuration file in JSON format
        :type config: io.BytesIO or argparse.FileType
        :return: the application config
        :rtype: dict
        """
        return json.load(config)

    @staticmethod
    def _load_yaml(config: Union[BytesIO, FileType]) -> dict:
        """Load a YAML config

        :param config: the configuration file in YAML format
        :type config: io.BytesIO or argparse.FileType
        :return: the application config
        :rtype: dict
        """
        return yaml.safe_load(config)

    @staticmethod
    def _validate(config_data: dict) -> None:
        """Validate the configuration meets expectations

        :param config_data: the loaded configuration
        :type config_data: dict
        :raises LookupError: when a required field is missing
        """
        if "authz" not in config_data:
            raise LookupError("authz is missing from the configuration")
        for key in ["backend", "config"]:
            if key not in config_data["authz"]:
                raise LookupError(f"{key} is missing from the authz configuration")
        for key in ["backend_cookie", "redirect_uri", "secret_type", "session_cookie"]:
            if key not in config_data["authz"]["config"]:
                raise LookupError(f"{key} is missing from authz.config")
        for key in ["application_name", "certificate", "client_id", "client_secret", "endpoint", "org_name"]:
            if key not in config_data["authz"]["backend"]:
                raise LookupError(f"{key} is missing from authz.backend")
        if "server_name" in config_data and config_data["server_name"] in [r".*", ".*"]:
            raise ValueError(
                f"rejecting server_name wildcard, please restrict host-matching e.g. {DEFAULTS['server_name']}"
            )

        config_data.setdefault("sep", {})
        config_data["sep"].setdefault(
            "processes",
            [
                {"name": "main", "asgi": False, "port": 8181, "host": "127.0.0.1"},
                {"name": "tasks", "asgi": True, "port": 8182, "host": "127.0.0.1"},
                {"name": "audit", "asgi": True, "port": 8183, "host": "127.0.0.1"},
            ],
        )
        if not config_data["sep"]:
            raise ValueError("sep.processes requires configuration")
        if not isinstance(config_data["sep"]["processes"], list) or not config_data["sep"]["processes"]:
            raise TypeError("sep.processes needs to be a list")


def launch(app: Union[Callable, str], config: Config, address: str, port: int):
    """Launch async process

    :param app:
    :param config:
    :param address:
    :param port:
    :return:
    """
    app_log.debug("Launching %s in process %d", app, getpid())

    async def _async_launch():
        if app == "main":
            application = Application(default_handler_class=DummyHandler, xsrf_cookies=True)
            application.config = config
            application.settings["cookie_secret"] = application.config.authz.SECRET_KEY
            application.settings["serve_traceback"] = application.config.sep.serve_traceback
            # Limit the host pattern to prevent DNS rebinding attacks
            # https://www.tornadoweb.org/en/stable/web.html#application-configuration
            application.add_handlers(application.config.server_name, application.config.get_handler_config())
            application.listen(port, address)
            await asyncio.Event().wait()
        else:
            await uvicorn.Server(
                uvicorn.Config(globals()[app], host=address, port=port, log_level=config.logging.value(), reload=False)
            ).serve()

    asyncio.run(_async_launch())


async def main(**kwargs) -> None:
    """Async entrypoint

    See sep.__main__ for the available kwargs
    The ones currently used are:
      config : the path to the config file
      logging: the level to set the log handler to
    """
    logging.basicConfig(
        level=kwargs["logging"],
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> " "%(module)s.%(funcName)s - %(message)s",
    )

    config = Config.load(config=kwargs.get("config"))
    config.logging = kwargs["logging"]
    config.lookups = ObjectDict()

    loop = asyncio.get_running_loop()
    with ProcessPoolExecutor(max_workers=len(config.sep.processes)) as pool:
        processes = []

        for i, process in enumerate(config.sep.processes):
            host, port, asgi = process["host"], process["port"], process["asgi"]

            match process["name"]:
                case "main":
                    config.lookups.main = i
                    processes.append(loop.run_in_executor(pool, launch, "main", config, host, port))
                case "audit" | "inventory" | "tasks":
                    config.lookups[process["name"]] = i
                    if asgi:
                        processes.append(
                            loop.run_in_executor(pool, launch, f"{process['name']}_app", config, host, port)
                        )
                case _:
                    # TODO: handle unexpected items, or configurable ASGI processes
                    pass

        try:
            await asyncio.gather(*processes)
        except (KeyboardInterrupt, asyncio.exceptions.CancelledError):
            for process in processes:
                if not process.cancelled():
                    process.cancel()
            loop.stop()
            loop.close()
            pool.shutdown()
