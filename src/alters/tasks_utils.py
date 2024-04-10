"""task related functions
"""

from typing import (
    Awaitable,
    Optional,
)

from sep.core import ApiBackendHandler
from sep.core.utils import async_request

TASK_API_ENDPOINT = "http://127.0.0.1:8182/"
INVENTORY_API_ENDPOINT = "http://127.0.0.1:8184/"


class AppWebHandler(ApiBackendHandler):
    """
    Handler with tasks related utils
    """

    TEMPLATE_PATH = "alters/index.html"

    async def _hosts(self) -> list:
        """List all hosts
        :param task:
        :return:
        """
        return await async_request(url=INVENTORY_API_ENDPOINT, request=self.request)

    async def _hosts_with_service(self, service_type: str) -> list:
        hosts = []
        for host in await self._hosts():
            for service in host["data"]["services"]:
                if service["type"] == service_type:
                    hosts.append(host)
        return hosts


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

    async def _execute_task(self, task_name: str) -> dict:
        """Trigger an archive task

        :param task_name:
        :return:
        """
        return await async_request(
            url=f"{TASK_API_ENDPOINT}execute/{task_name}",
            method="POST",
            request=self.request,
            payload={"task": task_name},
        )

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
        return await async_request(url=f"{TASK_API_ENDPOINT}?owner=alters", request=self.request)

    async def _task_history(self, task_name: str) -> list:
        """List the task history

        :param task_name:
        :return:
        """
        return await async_request(url=f"{TASK_API_ENDPOINT}history/{task_name}", request=self.request)

def build_alter_task_data(config):
    """
    returns a Job dict
    """

    payload = {
        "name": config["task_name"][0],
        "app": "alters",
        "commands": [
            {
                "args": [
                    f"--alter={config['alter'][0]}",
                    f"D={config['schema_name'][0]},t={config['table_name'][0]}",
                    "--execute"
                ],
                "command": "pt-online-schema-change",
                "meta": {
                    "schema_name": config['schema_name'][0],
                    "table_name": config['table_name'][0]
                }
            }
        ],
        "persist": True,
        "schedule": {"save_only": True},
        "target": config["hostname"][0],
    }
    return payload
