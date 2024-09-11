"""Models for Nomad tasks"""

import json

from pydantic import BaseModel


class Payload(BaseModel):
    """Generate a payload

    This is currently limited to supporting a single command
    and requires a small degree of knowledge about the backend.
    """

    app: str
    args: list = []
    commands: list = ""
    config: list = []
    meta: dict = {}
    name: str
    persist: bool = True
    schedule: dict = {"save_only": True}
    target: str = "THISISNOTAVALIDTARGET"

    def __dict__(self) -> dict:
        return {
            "name": self.name,
            "app": self.app,
            "commands": [
                {
                    "args": self.args,
                    "command": self.command,
                    "config": self.config,
                    "meta": self.meta,
                },
            ],
            "persist": self.persist,
            "schedule": self.schedule,
            "target": self.target,
        }

    def __str__(self) -> str:
        return json.dumps(self.__dict__, indent=None)
