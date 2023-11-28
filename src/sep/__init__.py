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
import importlib
from io import BytesIO
import json
import logging
import mimetypes
from os import environ
import pathlib
from secrets import token_bytes
from typing import (
    Any,
    Optional,
    Union,
)

from casdoor import (
    AsyncCasdoorSDK,
    CasdoorSDK,
)
from tornado.log import app_log
from tornado.web import Application
from tornado.util import ObjectDict
import yaml

from .authz import AuthZHandler
from .authz.casdoor import AuthzConfig
from .core import (
    DummyHandler,
    RemoteCallHandler,
)
from .tasks import TaskHandler
from .tasks.nomad import NomadRemoteCallHandler

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


class Config(ObjectDict):
    """
    Service Configuration
    """

    def __init__(self, data: dict, populate_defaults: bool = True):
        super().__init__(data)
        for k, v in data.copy().items():
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
        for i, handler in enumerate(self.handlers):
            # TODO: We could allow variable length here, as the third item could be empty,
            #       this can be decided later on though as explicit could be better than
            #       implicit here anyway.
            if HANDLER_DEFINITION_OPERATOR != "=":
                raise NotImplementedError("Handler definitions are currently fixed-length lists")
            if not isinstance(handler, list) or len(handler) != HANDLER_DEFINITION_LENGTH:
                app_log.warning("Deleting handler due to incompatibility: %s", handler)
                del self.handlers[i]
                continue
            try:
                if handler[1] not in ["RemoteCallHandler", "sep.RemoteCallHandler"]:
                    importlib.import_module(handler[1] if not handler[3] else handler[3])
            except ModuleNotFoundError:
                del self.handlers[i]
                continue
            if HANDLER_DEFINITION_REMOVE_AFTER:
                self.handlers[i] = self.handlers[i][0:HANDLER_DEFINITION_REMOVE_AFTER]
            app_log.debug("Handler %s loaded", handler[1])

        # Built-in rules
        self.handlers.append([r"/api/(?P<route>signin|signout)", AuthZHandler, {}])
        self.handlers.append([rf"^{TaskHandler.PATHS['ui']}(?P<route>(?!api|nomad).*)?$", TaskHandler, {}])

        # Tasks
        if hasattr(self, "modules") and "tasks" in self.modules and "api" in self.modules.tasks:
            self.handlers.append(
                [rf"^{TaskHandler.PATHS['api']}(?P<route>.*)?$", RemoteCallHandler, self.modules.tasks.api]
            )
        else:
            self.handlers.append(
                [rf"^{TaskHandler.PATHS['api']}(?P<route>.*)?$", RemoteCallHandler, {"uri": "http://127.0.0.1:8182"}]
            )
        # Nomad
        if hasattr(self, "modules") and "nomad" in self.modules and "api" in self.modules.nomad:
            self.handlers.append(
                [
                    rf"^{NomadRemoteCallHandler.PATHS['base']}(?P<route>.+)$",
                    NomadRemoteCallHandler,
                    self.modules.nomad.api,
                ]
            )
        else:
            self.handlers.append(
                [
                    rf"^{NomadRemoteCallHandler.PATHS['base']}(?P<route>.+)$",
                    NomadRemoteCallHandler,
                    {"uri": "http://127.0.0.1:4646"},
                ]
            )

        return self.handlers

    @staticmethod
    def load(config: Union[BytesIO, FileType], mimetype: Optional[str | bytes] = None) -> "Config":
        """Generate a Config instance

        :param config: the configuration file in JSON, or YAML format
        :type config: io.BytesIO or argparse.FileType
        :param mimetype: optionally set the mimetype to avoid guessing from the filename
        :type mimetype: str, bytes
        :return: the configuration object
        :rtype: Config (ObjectDict)
        """
        app_log.info("Loading config from %s", config)
        if not mimetype:
            path = pathlib.Path(config.name)
            mimetype = mimetypes.guess_type(path.absolute())
        config_data = Config._load_json(config) if "application/json" in mimetype else Config._load_yaml(config)

        # Validate
        Config._validate(config_data)

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
            SECRET_KEY=token_bytes(24),
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


async def main(**kwargs) -> None:
    """Async entrypoint

    See sep.__main__ for the available kwargs
    The ones currently used are:
      config :   the path to the config file
      log_level: the level to set the log handler to
    """
    logging.basicConfig(
        level=kwargs["log_level"],
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> " "%(module)s.%(funcName)s - %(message)s",
    )
    app = Application(default_handler_class=DummyHandler, xsrf_cookies=True)
    app.config = Config.load(config=kwargs.get("config"))
    app.settings["cookie_secret"] = app.config.authz.SECRET_KEY
    # Limit the host pattern to prevent DNS rebinding attacks
    # https://www.tornadoweb.org/en/stable/web.html#application-configuration
    app.add_handlers(app.config.server_name, app.config.get_handler_config())
    app.listen(app.config.port)
    await asyncio.Event().wait()
