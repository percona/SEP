"""
Nomad
"""
from asyncio import sleep
import json

import nomad
from tornado.log import app_log

from sep.core import RemoteCallHandler
from sep.core.db import (
    Database,
    get_timestamp,
)
from sep.tasks.api.models import (
    history,
    Task,
    TaskExecutionRequest,
    TASK_HISTORY_STATUS_MAP,
)

__all__ = ["NomadRemoteCallHandler"]


class NomadRemoteCallHandler(RemoteCallHandler):
    """Handler to send requests directly to Nomad"""

    PATHS = {"base": "nomad/"}

    def initialize(self, **kwargs) -> None:
        """Hook for local config loading"""
        super().initialize(**kwargs)

        if hasattr(self.cfg, "modules") and "nomad" in self.cfg.modules and "request_options" in self.cfg.modules.nomad:
            self.request_options.update(self.cfg.modules.nomad.request_options)


class Executor:
    backend: nomad.Nomad
    database: Database
    execution_request: TaskExecutionRequest
    task: Task

    def __init__(self, cfg: dict, database: Database, execution_request: TaskExecutionRequest, task: Task) -> None:
        """Configure the executor

        :param cfg:
        :param database:
        :param execution_request:
        :param task:
        :return:
        """
        self.backend = nomad.Nomad(**cfg)
        self.database = database
        self.execution_request = execution_request
        self.task = task

    async def run(self, queue_item: dict, interval: int) -> None:
        queue_id = queue_item["id"]

        # TODO: determine scenarios for execution, such as looking up an existing job
        task_data = json.loads(self.task.data)
        if queue_item["execution_request"].get("meta"):
            # TODO: target is currently pushed in to meta
            queue_item["execution_request"]["meta"]["target"] = queue_item["execution_request"]["target"]
            # TODO: DC is currently forced
            queue_item["execution_request"]["meta"]["dc"] = "dc1"
            # TODO: allow templates in more fields, currently only for constraints
            for meta_var, meta_val in queue_item["execution_request"]["meta"].items():
                for i, constraint in enumerate(task_data["Constraints"]):
                    meta = "${NOMAD_META_" + meta_var + "}"
                    task_data["Constraints"][i] = json.loads(json.dumps(constraint).replace(meta, meta_val))

        try:
            job = self.backend.job.get_job(self.task.name)
            status = self.backend.job.evaluate_job(self.task.name)
        except nomad.api.exceptions.BaseNomadException:
            status = self.backend.jobs.register_job({"Job": task_data})
            app_log.debug("Job status: %r", status)
            job = self.backend.job.get_job(self.task.name)

        self.execution_request.tracking.update(evaluation_id=status["EvalID"])
        async with self.database.engine.begin() as conn:
            await conn.execute(
                history.update().where(history.c.id == queue_id).values(execution_request=self.execution_request)
            )

        allocation_filters = [f'JobID == "{job["ID"]}"', f'EvalID == "{status["EvalID"]}"']
        allocations = self.backend.allocations.get_allocations(filter_=" && ".join(allocation_filters))
        app_log.debug("Job: %r", job)
        app_log.debug("Allocations: %r", [x["JobID"] for x in allocations])

        if job["ParameterizedJob"]:
            # Example content:
            # "ParameterizedJob": {"MetaOptional": ["args", "image"], "MetaRequired": ["command"], "Payload": ""}
            # https://python-nomad.readthedocs.io/en/latest/api/job/#dispatch-job
            raise NotImplementedError("Parameterized job support is TBD")

        async with self.database.engine.begin() as conn:
            await conn.execute(
                history.update()
                .where(history.c.id == queue_id)
                .values(status=TASK_HISTORY_STATUS_MAP["running"], updated_at=get_timestamp())
            )

        alloc = allocations[0]
        while True:
            match job["Type"]:
                case "batch":
                    raise NotImplementedError("Batch job support is TBD")
                case "service":
                    raise NotImplementedError("Service job support is TBD")
                case "system" | "sysbatch":
                    alloc = self.backend.allocations.get_allocations(filter_=f'EvalID == "{alloc["EvalID"]}"')[0]
                case _:
                    raise NotImplementedError(f'Unrecognized job type \'{job["Type"]}\'')
            if alloc["ClientStatus"] in ["completed", "failed"]:
                break
            await sleep(interval)
        # Check status
        status = 0
        if alloc["ClientStatus"] == "failed":
            for state in alloc["TaskStates"].values():
                status += sum([x["ExitCode"] for x in state["Events"]])

        self.execution_request.tracking.update(task_states=alloc["TaskStates"])
        async with self.database.engine.begin() as conn:
            await conn.execute(
                history.update()
                .where(history.c.id == queue_id)
                .values(
                    status=TASK_HISTORY_STATUS_MAP["failed" if status > 0 else "success"],
                    updated_at=get_timestamp(),
                    execution_request=self.execution_request,
                )
            )
