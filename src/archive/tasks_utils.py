"""task related functions"""

from typing import Union

from typing import (
    Awaitable,
    Optional,
)

import yaml

from sep.core import ApiBackendHandler
from sep.core.utils import async_request

# FIXME: This is just plain wrong :)
TASK_API_ENDPOINT = "http://127.0.0.1:8182/"
INVENTORY_API_ENDPOINT = "http://127.0.0.1:8184/"

PURGE_TABLES_CONFIG_WHERE = {
    "ALL": {"SOURCE_HOST": None, "SOURCE_PORT": 0},
    "PURGE_LIST": [{"ALIAS": None, "SOURCE_DB": None, "SOURCE_TABLE": None, "DEST_TABLE": None, "WHERE": None}],
}


# FIXME: this is bypassing authentication by not using the correct handler
class AppWebHandler(ApiBackendHandler):
    """
    Handler with tasks related utils
    """

    def initialize(self) -> None:
        """
        Perform setup tasks

        :return:
        """
        super().initialize()
        self.data.update(template_path="index.html")
        # self.data.update(template_path="index.html", template_data={
        #   "hosts": [],
        #   "archives": [],
        #   "scheduled_tasks": [],
        #   "history_tasks": [],
        #   "running_tasks": [],
        # })
        self.cfg.templates.update(dirs=["#resolve#../templates/archiver"])

    def data_received(self, chunk: bytes) -> Optional[Awaitable[None]]:
        pass

    async def _hosts(self) -> list:
        """List all hosts
        :param task:
        :return:
        """
        return await async_request(url=INVENTORY_API_ENDPOINT, request=self.request)

    async def _create_task(self, task_payload: dict) -> dict:
        """Create a task
        :param task_payload:
        :return:
        """
        return await async_request(
            url=f"{TASK_API_ENDPOINT}generate", method="POST", request=self.request, payload=task_payload
        )

    async def _delete_task(self, task_name: str) -> dict:
        """Delete a task

        :param task_name:
        :return:
        """
        return await async_request(url=f"{TASK_API_ENDPOINT}{task_name}", method="DELETE", request=self.request)

    async def _get_task(self, task_name: str) -> dict:
        """Returns details for a single task

        :param task_name:
        :return:
        """
        return await async_request(url=f"{TASK_API_ENDPOINT}{task_name}", request=self.request)

    async def _get_task_stats(self, task_name: str) -> dict:
        """Get the stats for a task

        :param task_name:
        :return:
        """
        return await async_request(url=f"{TASK_API_ENDPOINT}stats/{task_name}", request=self.request)

    async def _list_tasks(self) -> list:
        """Returns a list of tasks"""
        # TODO: consider how to filter automatically based upon app ID
        return await async_request(url=f"{TASK_API_ENDPOINT}?owner=archiver", request=self.request)

    async def _task_history(self, task_name: str) -> list:
        """List the task history

        :param task_name:
        :return:
        """
        return await async_request(url=f"{TASK_API_ENDPOINT}history/{task_name}", request=self.request)


def build_archive_task_data(config):
    """
    returns a Job dict
    """
    match config["archive_type"]:
        case ["where"]:
            purge_config = PURGE_TABLES_CONFIG_WHERE.copy()
        case _:
            raise NotImplementedError("Currently only 'where' is supported")

    purge_config_all = purge_config["ALL"]
    purge_config_list = purge_config["PURGE_LIST"][0]
    purge_config_all.update(SOURCE_HOST=config["hostname"][0], SOURCE_PORT=3306)
    purge_config_list.update(
        ALIAS=config["task_name"][0],
        SOURCE_DB=config["sourcedb"][0],
        SOURCE_TABLE=config["sourcetbl"][0],
        DEST_TABLE=config["desttbl"][0],
        WHERE=config["where"][0],
    )
    purge_config.update(ALL=purge_config_all, PURGE_LIST=[purge_config_list])

    payload = {
        "name": config["task_name"][0],
        "app": "archiver",
        "commands": [
            {
                "args": [
                    f"--alias={config['task_name'][0]}",
                    "--config=${NOMAD_TASK_DIR}/purge_tables.yaml",
                ],
                "command": "/home/percona/bin/purge-tables.py",
                "config": [
                    {
                        "content": yaml.dump(purge_config),
                        "path": "purge_tables.yaml",
                    }
                ],
            }
        ],
        "persist": True,
        "schedule": {"save_only": True},
        "target": config["hostname"][0],
    }
    return payload


def extract_task_values(config: Union[dict, str], items: list) -> dict:
    """Extract data from the task's config file

    :param config:
    :param items:
    :return:
    """
    if not isinstance(config, dict):
        try:
            config = yaml.safe_load(config)
        except yaml.YAMLError:
            return {}
    data = {}
    for item in items:
        match item:
            case "hostname":
                data[item] = config["ALL"]["SOURCE_HOST"]
            case "name":
                data[item] = config["PURGE_LIST"][0]["ALIAS"]
            case "table":
                data[item] = f'{config["PURGE_LIST"][0]["SOURCE_DB"]}.{config["PURGE_LIST"][0]["SOURCE_TABLE"]}'
            case _:
                data[item] = config.get(item)
    return data
