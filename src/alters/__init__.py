"""
Add to config.py handlers

[r"^/alters/(?P<route>.*)?$", "alters.AlterHandler", {}, "alters"]
"""

import json
from http import HTTPStatus


from urllib.parse import parse_qs
from tornado.log import app_log
from tornado.web import HTTPError
import yaml

from sep.tasks.api.models import TASK_HISTORY_STATUS_LOOKUP

from . import tasks_utils


class AlterHandler(tasks_utils.AppWebHandler):
    """
    Dummy handler use for all unrouted requests
    """

    async def get(self, route) -> None:
        """Server GET requests"""

        if route:
            route_path = route.split("/")

            match route_path[0]:
                #case "delete":
                #    app_log.debug("DELETE: %s", route_path[1])
                #    await self._delete_task(route_path[1])
                case "details":
                    await self._alter_view_details(route_path[1])
                    return

        hosts = await self._hosts()
        tasks = await self._formated_alter_tasks()

        scheduled_tasks = []
        history_tasks = []
        running_tasks = []
        for task in tasks:
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
                "tasks": tasks,
                "scheduled_tasks": scheduled_tasks,
                "history_tasks": history_tasks,
                "running_tasks": running_tasks,
            }
        )

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
                await self._create_task(tasks_utils.build_alter_task_data(payload))
        self.redirect(redirect)

        #task = self._build_alter_task_data(payload)
        #task_payload = self._build_task_payload(task)
        #await self._create_task(task_payload)
        #self.redirect("/alters/")

    async def _alter_view_details(self, task_name):
        """Handles detailed
        archive view
        """
        task = await self._get_task(task_name)
        data = json.loads(task["data"])
        app_log.debug("TASK DETAIL: %s", task)

        task_config = data["TaskGroups"][0]["Tasks"][0]["Config"]
        meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
        self.data.update(
            template_path="alters/details.html",
            template_data={
                "history": await self._task_history(task_name),
                "stats": await self._get_task_stats(task_name),
                "task_name": task_name,
                "task": {
                    "created_at": task["created_at"],
                    "updated_at": task["updated_at"],
                    "hostname": data["Constraints"][0]["RTarget"],
                    "table": f'{meta["schema_name"]}.{meta["table_name"]}',
                    "cmd": f'{task_config["command"]} {" ".join(task_config["args"])}',
                    "meta": meta
                }
            }
        )

        #details = {}
        #details["created_at"] = task["created_at"]
        #details["updated_at"] = task["updated_at"]
        #details["hostname"] = data["Job"]["Constraints"][0]["RTarget"]
        #details["table"] = f"{meta['sourcedb']}.{meta['sourcetable']}"
        #details["cmd"] = (
        #   data["Job"]["TaskGroups"][0]["Tasks"][0]["Config"]["command"]
        #    + " "
        #    + " ".join(data["Job"]["TaskGroups"][0]["Tasks"][0]["Config"]["args"])
        #)
        #details["meta"] = meta

        #history = await self._task_history(task_name)
        #self.render("../../templates/alters/details.html", task_name=task_name, task=details, history=history)

    # Used?
    async def _alter_tasks(self) -> list:
        tasks = await self._list_tasks()
        return [x for x in tasks if x["name"].startswith("alter")]

    async def _formated_alter_tasks(self) -> list:
        alters = []
        for task in await self._list_tasks():
            print(task)
            try:
                data = json.loads(task["data"])
                print(data)
                try:
                    meta = data["TaskGroups"][0]["Tasks"][0]["Meta"]
                    taskinfo = {
                        "hostname": data["Constraints"][0]["RTarget"],
                        "name": task["name"],
                        "table": f'{meta["schema_name"]}.{meta["table_name"]}'
                    }
                except (KeyError, IndexError):
                    taskinfo = {"hostname": "Unknown", "name": "Unknown", "table": "Unknown"}
                taskinfo.update(id=task["id"])
                alters.append(taskinfo)
            except (KeyError, IndexError):
                continue
            #data = json.loads(b64decode(task["data"]))
            #meta = data["Job"]["TaskGroups"][0]["Tasks"][0]["Meta"]
            #table = f"{meta['sourcedb']}.{meta['sourcetable']}"
            #alters.append(
            #    {"name": task["name"], "hostname": data["Job"]["Constraints"][0]["RTarget"], "table": table}
            #)
        print(alters)
        return alters
