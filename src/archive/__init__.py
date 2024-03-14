"""
Add to config.py handlers

[r"^/archive/(?P<route>.*)?$", "archive.ArchiveHandler", {}, "archive"]
"""

import json
from http import HTTPStatus

from tornado.log import app_log
from tornado.web import HTTPError
from urllib.parse import parse_qs
import yaml

from sep.tasks.api.models import TASK_HISTORY_STATUS_LOOKUP

from . import tasks_utils


class ArchiveHandler(tasks_utils.AppWebHandler):
    """
    Dummy handler use for all unrouted requests
    """

    async def get(self, route) -> None:
        """Server GET requests"""

        if route:
            route_path = route.split("/")

            match route_path[0]:
                case "delete":
                    app_log.debug("DELETE: %s", route_path[1])
                    await self._delete_task(route_path[1])
                case "details":
                    await self._archive_view_details(route_path[1])
                    return

        hosts = await self._hosts()
        archives = await self._formatted_archive_tasks()

        scheduled_tasks = []
        history_tasks = []
        running_tasks = []
        for task in archives:
            history = await self._task_history(task["name"])
            for hist in history:
                match TASK_HISTORY_STATUS_LOOKUP[hist["status"]]:
                    case "success" | "failed":
                        history_tasks.append(hist)
                    case "pending":
                        scheduled_tasks.append(hist)
                    case "running":
                        running_tasks.append(hist)
        self.data.update(
            template_data={
                "hosts": hosts,
                "archives": archives,
                "scheduled_tasks": scheduled_tasks,
                "history_tasks": history_tasks,
                "running_tasks": running_tasks,
            }
        )

    async def post(self, route) -> None:
        """Serve POST requests"""
        payload = parse_qs(self.request.body.decode())
        app_log.debug("Received POST: %s", payload)
        await self._create_task(tasks_utils.build_archive_task_data(payload))
        self.redirect(self.request.uri)

    async def _archive_view_details(self, task_name):
        """Handles detailed archive view"""
        task = await self._get_task(task_name)
        data = json.loads(task["data"])

        try:
            meta = yaml.safe_load(data["TaskGroups"][0]["Tasks"][0]["Templates"][0]["EmbeddedTmpl"])
        except yaml.YAMLError:
            app_log.exception("Error parsing archive view")
            raise HTTPError(status_code=HTTPStatus.EXPECTATION_FAILED, log_message="Failed to load template data")
        app_log.debug("TASK DETAIL: %s", task)

        task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
        await self.render(
            "./templates/archive_details.html",
            history=await self._task_history(task_name),
            stats=await self._get_task_stats(task_name),
            task_name=task_name,
            task={
                "created_at": task["created_at"],
                "updated_at": task["updated_at"],
                "cmd": f'{task_config["command"]} {" ".join(task_config["args"])}',
                "meta": meta,
                "table": f'{meta["PURGE_LIST"][0]["SOURCE_DB"]}.{meta["PURGE_LIST"][0]["SOURCE_TABLE"]}',
                "hostname": meta["ALL"]["SOURCE_HOST"],
            },
        )

    async def _formatted_archive_tasks(self) -> list:
        archives = []
        for task in await self._list_tasks():
            try:
                # TODO: this is engine-specific
                templates = json.loads(task["data"])["TaskGroups"][0]["Tasks"][0]["Templates"]
                try:
                    meta = tasks_utils.extract_task_values(templates[0]["EmbeddedTmpl"], ["hostname", "name", "table"])
                except (KeyError, IndexError):
                    meta = {"hostname": "Unknown", "name": "Unknown", "table": "Unknown"}
                meta.update(id=task["id"])
                archives.append(meta)
            except (KeyError, IndexError):
                continue
        return archives
