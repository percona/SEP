"""
SEP: Services Enablement Platform

Example config (JSON):
{
    "authz": {
        "backend": {
            "application_name": "<app-name>",
            "certificate": "<single-line-cert-as-string> | <env-var> | <file-path>",
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
    AnyStr,
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
from .core import DummyHandler

__all__ = []
__version__ = "0.0.1"

DEFAULT_SERVER_MATCH = r"^((127\.([0-9]{1,3}\.){2}[0-9]{1,3})|localhost)$"
HANDLER_DEFINITION_LENGTH = 4
HANDLER_DEFINITION_OPERATOR = "="
HANDLER_DEFINITION_REMOVE_AFTER = 3


class Config(ObjectDict):
    """
    Service Configuration
    """

    def get_handler_config(self) -> list:
        """Generate the config to set the app handlers"""
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
        self.handlers.append(["/api/(?P<route>signin|signout)", AuthZHandler, {}])
        return self.handlers

    @staticmethod
    def load(config: Union[BytesIO, FileType], mimetype: Union[None, AnyStr] = None) -> "Config":
        """Generate a Config instance"""
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
        """Load a JSON config"""
        return json.load(config)

    @staticmethod
    def _load_yaml(config: Union[BytesIO, FileType]) -> dict:
        """Load a YAML config"""
        return yaml.safe_load(config)

    @staticmethod
    def _validate(config_data: dict):
        """

        :param config_data:
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


async def main(**kwargs):
    """Async entrypoint"""
    logging.basicConfig(
        level=kwargs["log_level"],
        format="%(asctime)s %(levelname)s:%(name)s: PID<%(process)d> " "%(module)s.%(funcName)s - %(message)s",
    )
    app = Application(default_handler_class=DummyHandler, xsrf_cookies=True)
    app.config = Config.load(config=kwargs.get("config"))
    app.settings["cookie_secret"] = app.config.authz.SECRET_KEY
    # Use default_host to prevent DNS rebinding attacks
    # https://www.tornadoweb.org/en/stable/web.html#application-configuration
    app.add_handlers(app.config.get("server_name", DEFAULT_SERVER_MATCH), app.config.get_handler_config())
    app.listen(app.config.port)
    await asyncio.Event().wait()
