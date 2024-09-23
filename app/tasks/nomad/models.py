"""Define models for Nomad tasks"""

import json

from pydantic import BaseModel


class Payload(BaseModel):
    """Represent a task payload for Nomad.

    This model is used to generate a payload that can be sent to the Nomad backend.
    It supports a single command and requires some knowledge of the backend
    configuration.

    Attributes
    ----------
    app : str
        The application name associated with the task.
    args : list
        The arguments for the command. Defaults to an empty list.
    commands : list
        The list of commands to execute. Defaults to an empty string.
    config : list
        Configuration details for the task. Defaults to an empty list.
    meta : dict
        Metadata associated with the task. Defaults to an empty dictionary.
    name : str
        The name of the task.
    persist : bool
        Whether the task should persist to the db after execution. Defaults to True.
    schedule : dict
        The scheduling configuration for the task. Defaults to {"save_only": True}.
    target : str
        The target environment for the task. Defaults to "THISISNOTAVALIDTARGET".

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
