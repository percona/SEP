"""
Nomad
"""
from sep.core import RemoteCallHandler

__all__ = ["NomadRemoteCallHandler"]


class NomadRemoteCallHandler(RemoteCallHandler):
    """Handler to send requests directly to Nomad"""

    PATHS = {"base": "nomad/"}

    def initialize(self, **kwargs) -> None:
        """Hook for local config loading"""
        super().initialize(**kwargs)

        if hasattr(self.cfg, "modules") and "nomad" in self.cfg.modules and "request_options" in self.cfg.modules.nomad:
            self.request_options.update(self.cfg.modules.nomad.request_options)
