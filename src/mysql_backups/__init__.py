"""
MySQL Backup App

---
Add to config.py handlers

[r"^/mysql_backups/(?P<route>.*)?$", "MysqlBackupsHandler", {}, "mysql_backups"]
"""

import json
from http import HTTPStatus


from urllib.parse import parse_qs
from tornado.log import app_log
from tornado.web import HTTPError

from sep.core import TaskApiBackendHandler
from sep.core.models import Widget
from sep.tasks.api.models import (
    TASK_HISTORY_STATUS_LOOKUP,
    TASK_HISTORY_STATUS_MAP
)

from .utils import (
    build_task_payload,
    extract_task_values,
)


class MysqlBackupsHandler(TaskApiBackendHandler):
    """
    MySQL Backup Handler
    """

    OWNER = "mysql_backups"
    TEMPLATE_PATH = "mysql_backups/index.html"

    async def get(self, route) -> None:
        """Server GET requests"""

        route_path = route.split("/")
        api_request = False

        match route_path[0]:
            case "api":
                api_request = True
            case "host":
                await self._backup_view_host(route_path[1])
                return

        hosts = await self._hosts_with_service("mysql")
        backups = await self._formatted_backup_tasks([x["name"] for x in hosts])
        environments = []

        for host in hosts:
            for service in host['data']['services']:
                environments.append(service['environment'])

        self.data.update(
            template_data={
                "hosts": hosts,
                "environments": set(environments),
                "backups": backups,
            }
        )
        if api_request:
            raise HTTPError(status_code=HTTPStatus.NOT_FOUND)

    async def _backup_view_host(self, host_name):
        """Handles detailed view"""

        hosts = await self._hosts_with_service("mysql")
        environments = []

        for host in hosts:
            for service in host['data']['services']:
                environments.append(service['environment'])

        backups = await self._formatted_backup_tasks([host_name])

        scheduled_tasks = []
        history_tasks = []
        running_tasks = []
        for backup in backups[host_name]:
            history = await self._task_history(backup['task_name'])
            for hist in history:
                match TASK_HISTORY_STATUS_LOOKUP[hist["status"]]:
                    case "success" | "failed":
                        history_tasks.append(hist)
                    case "pending":
                        scheduled_tasks.append(hist)
                    case "running":
                        running_tasks.append(hist)

        self.data.update(
            template_path="mysql_backups/host.html",
            template_data={
                "hosts": hosts,
                "environments": set(environments),
                "backups": backups,
                "history_tasks": history_tasks
            }
        )

    async def post(self, route) -> None:
        """Serve POST requests"""
        payload = parse_qs(self.request.body.decode())
        app_log.debug("Received POST: %s", payload)
        self._xsrf_to_headers(payload)

        redirect = self.request.uri
        route_path = route.split("/")
        match route_path[0]:
            case "execute":
                app_log.debug("Executing: %s", route_path[1])
                await self._execute_task(route_path[1])
                redirect = ""
            case "":
                await self._create_task(dict(build_task_payload(payload)))
        self.redirect(redirect)

    async def _formatted_backup_tasks(self, hosts) -> list:
        """
        returns a list of backup tasks filtered by a host list
        """
        backups = {}
        for task in await self._list_tasks():
            try:
                task_data = json.loads(task["data"])
                backup_host = task_data["Constraints"][0]["RTarget"]

                # This filter might be moved to _list_tasks in the future
                if backup_host in hosts:
                    templates = task_data["TaskGroups"][0]["Tasks"][0]["Templates"]
                    try:
                        meta = extract_task_values(templates[0]["EmbeddedTmpl"], ["hostname", "name", "type", "all"])
                    except (KeyError, IndexError):
                        meta = {"hostname": "Unknown", "name": "Unknown", "table": "Unknown"}
                    meta.update(id=task["id"])
                    meta.update(task_name=task["name"])
                    meta.update(backup_host=backup_host)
                    if backup_host not in backups:
                        backups[backup_host] = []
                    backups[backup_host].append(meta)
            except (KeyError, IndexError) as exc:
                app_log.exception(exc)
                continue
        return backups


    async def _hosts_with_service(self, service_type: str) -> list:
        hosts = []
        for host in await self._hosts():
            for service in host["data"]["services"]:
                if service["type"] == service_type:
                    hosts.append(host)
        return hosts
