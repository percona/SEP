"""
Nomad
"""
from .. import TaskHandler
from sep.core import RemoteCallHandler

__all__ = ["NomadRemoteCallHandler"]


class NomadRemoteCallHandler(RemoteCallHandler):
    """Handler to send requests directly to Nomad"""

    PATHS = {
        "base": f"{TaskHandler.PATHS['ui']}nomad/",
    }

    def initialize(self, **kwargs) -> None:
        """Hook for local config loading"""
        super().initialize(**kwargs)

        if hasattr(self.cfg, "modules") and "nomad" in self.cfg.modules and "request_options" in self.cfg.modules.nomad:
            self.request_options.update(self.cfg.modules.nomad.request_options)

    # Note: the Nomad UI does not seem to be configurable to set the path,
    #       so we can't act like a proxy to the UI and provide authentication via Casdoor
    # def write(self, chunk: Union[str, bytes, dict]) -> None:
    #    """Special handling for writing out content
    #    :param chunk:
    #    :return:
    #    """
    #    output = ""
    #    if isinstance(chunk, dict):
    #        output = chunk
    #    elif isinstance(chunk, bytes):
    #        output = chunk.replace(b"<head>", f'<head><base href="{self.request.uri}">'.encode("utf-8"))
    #    else:
    #        output = chunk.replace("<head>", f'<head><base href="{self.request.uri}">')
    #    super().write(output)
