# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Build a delivery-plan executor over a pooled transport for a configured plan.

The transport client is pooled per origin and derives its own base path, so a
configured endpoint carrying a path prefix or query string cannot be handed to
the client wholesale -- those parts are rebased onto the plan's own steps here.
"""

__all__ = ["get_delivery_executor", "split_endpoint"]

from urllib.parse import parse_qsl, urlparse

from app.core.config import settings
from app.core.requests import RemoteAPI
from app.sep.bundle_upload.plan import (
    DeliveryPlan,
    DeliveryPlanExecutor,
    LiteralValue,
    PlanValue,
    StepObserver,
)


def split_endpoint(endpoint: str) -> tuple[str, str, dict[str, str]]:
    """Split a configured endpoint into origin, request path, and query pairs.

    The transport client is pooled per origin and derives its own base path, so
    the path and query travel in the plan instead. Repeated query keys collapse
    to the last occurrence.

    :param endpoint: The configured upload endpoint URL.
    :return: The scheme-and-host origin, the request path, and the query pairs.
    """
    parsed = urlparse(endpoint)
    return (
        f"{parsed.scheme}://{parsed.netloc}",
        parsed.path or "/",
        dict(parse_qsl(parsed.query)),
    )


def _rebase_path(prefix: str, path: str) -> str:
    """Prefix a step path with the endpoint's path, if it carries one.

    :param prefix: The endpoint's path, ``"/"`` when it carries none.
    :param path: The step's configured path.
    :return: The step path resolved under the endpoint's path.
    """
    if prefix == "/":
        return path
    return f"{prefix.rstrip('/')}/{path.lstrip('/')}"


def _rebase_query(
    query: dict[str, PlanValue], endpoint_query: dict[str, str]
) -> dict[str, PlanValue]:
    """Merge the endpoint's query pairs into a step's own, without displacing them.

    :param query: The step's configured query map.
    :param endpoint_query: The query pairs carried by the configured endpoint.
    :return: The merged query map.
    """
    merged = {
        key: LiteralValue(source="literal", value=value)
        for key, value in endpoint_query.items()
    }
    merged.update(query)
    return merged


def _rebased_plan(
    plan: DeliveryPlan, *, path: str, query: dict[str, str]
) -> DeliveryPlan:
    """Return a copy of ``plan`` with the endpoint's path and query on every step.

    Pydantic's ``model_copy`` is shallow, so each nested step is rebuilt rather
    than shared: the plan handed in is the process-global configured one, and
    mutating its steps would corrupt every later send.

    :param plan: The configured plan to rebase.
    :param path: The endpoint's path.
    :param query: The endpoint's query pairs.
    :return: A rebased copy leaving ``plan`` and its steps untouched.
    """
    steps = [
        step.model_copy(
            update={
                "path": _rebase_path(path, step.path),
                "query": _rebase_query(step.query, query),
            }
        )
        for step in plan.resolution_steps
    ]
    upload = plan.upload.model_copy(
        update={
            "path": _rebase_path(path, plan.upload.path),
            "query": _rebase_query(plan.upload.query, query),
        }
    )
    return plan.model_copy(update={"resolution_steps": steps, "upload": upload})


async def get_delivery_executor(
    plan: DeliveryPlan, *, step_observer: StepObserver | None = None
) -> DeliveryPlanExecutor:
    """Build an executor for ``plan`` over a transport pooled on its origin.

    :param plan: The configured delivery plan to run.
    :param step_observer: A synchronous callback notified as each resolution step
        starts and completes, for a caller that records send progress.
    :return: The executor bound to the plan and its transport.
    """
    origin, path, query = split_endpoint(str(plan.endpoint))
    if path != "/" or query:
        plan = _rebased_plan(plan, path=path, query=query)
    api = await settings.get_remote_api(RemoteAPI, endpoint=origin)
    return DeliveryPlanExecutor(plan, api, step_observer=step_observer)
