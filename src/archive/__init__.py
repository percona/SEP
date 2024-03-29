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

from sep.core.models import Widget
from sep.tasks.api.models import (
    TASK_HISTORY_STATUS_LOOKUP,
    TASK_HISTORY_STATUS_MAP,
)

from . import tasks_utils


class ArchiveHandler(tasks_utils.AppWebHandler):
    """
    Dummy handler use for all unrouted requests
    """

    async def get(self, route) -> None:
        """Server GET requests"""

        route_path = route.split("/")
        api_request = False

        match route_path[0]:
            case "api":
                api_request = True
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
        if api_request:
            if len(route_path) == 1:
                route_path.append("")
            match route_path[1]:
                case "widget":
                    self.set_header("Content-Type", "application/json")
                    self.data.update(template_path=f"archiver/api.json")
                    self.data["template_data"] = await self._widget()
                case _:
                    raise HTTPError(status_code=HTTPStatus.NOT_FOUND)

    async def post(self, route) -> None:
        """Serve POST requests"""
        payload = parse_qs(self.request.body.decode())
        app_log.debug("Received POST: %s", payload)

        redirect = self.request.uri
        route_path = route.split("/")
        match route_path[0]:
            case "delete":
                app_log.debug("DELETE: %s", route_path[1])
                await self._delete_task(route_path[1])
            case "details":
                app_log.debug("Viewing: %s", route_path[1])
            case "execute":
                app_log.debug("Executing: %s", route_path[1])
                await self._execute_task(route_path[1])
                redirect = ""
            case "":
                await self._create_task(tasks_utils.build_archive_task_data(payload))
        self.redirect(redirect)

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
        self.data.update(
            template_path="archiver/details.html",
            template_data={
                "history": await self._task_history(task_name),
                "stats": await self._get_task_stats(task_name),
                "task_name": task_name,
                "task": {
                    "created_at": task["created_at"],
                    "updated_at": task["updated_at"],
                    "cmd": f'{task_config["command"]} {" ".join(task_config["args"])}',
                    "meta": meta,
                    "table": f'{meta["PURGE_LIST"][0]["SOURCE_DB"]}.{meta["PURGE_LIST"][0]["SOURCE_TABLE"]}',
                    "hostname": meta["ALL"]["SOURCE_HOST"],
                },
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

    async def _widget(self) -> dict | list:
        """Generate widget data

        {
          "heading": "Data archiver",
          "data": [
            {"heading": "Running tasks", "data": []},
            {"heading": "Scheduled tasks", "data": []},
            {"heading": "Recent problems", "data": []},
          ],
          "layout": "table",
          "multipart": true
        }

        :return:
        """
        widget = Widget(heading="Data archiver", data=[], layout="table", multipart=True)
        data = self.data.get("template_data")
        if not data or not {"history_tasks", "running_tasks", "scheduled_tasks"}.issubset(set(data.keys())):
            return widget.model_dump()

        failed_tasks_widget = Widget(heading="Recent issues", data=[], layout="table")
        running_tasks_widget = Widget(heading="Running tasks", data=[], layout="table")
        scheduled_tasks_widget = Widget(heading="Scheduled tasks", data=[], layout="table")

        for item in data["history_tasks"]:
            if item["status"] == TASK_HISTORY_STATUS_MAP["success"]:
                continue
            job_data = json.loads(item["data"]["data"])
            failed_tasks_widget.data.append(
                {
                    "task": item["name"],
                    "host": job_data["Constraints"][0]["RTarget"],
                    "duration": round(item["execution_request"]["tracking"]["duration"], 3),
                    "started_at": item["execution_request"]["tracking"]["started_at"],
                    "finished_at": item["execution_request"]["tracking"]["finished_at"],
                    "errors": item["errors"]
                }
            )
        # TODO: chopping off from the last 5 failures for now
        failed_tasks_widget.data = failed_tasks_widget.data[-5:]

        for item in data["running_tasks"]:
            job_data = json.loads(item["data"]["data"])
            running_tasks_widget.data.append(
                {
                    "task": item["name"],
                    "host": job_data["Constraints"][0]["RTarget"],
                    "started_at": item["execution_request"]["tracking"]["started_at"],
                }
            )
        for item in data["scheduled_tasks"]:
            job_data = json.loads(item["data"]["data"])
            scheduled_tasks_widget.data.append(
                {
                    "task": item["name"],
                    "host": job_data["Constraints"][0]["RTarget"],
                }
            )

        for subwidget in [failed_tasks_widget, running_tasks_widget, scheduled_tasks_widget]:
            widget.data.append(subwidget.model_dump())
        return widget.model_dump()
