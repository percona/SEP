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

"""Define the admin-only ``/api/sep/admin/delivery-connection`` endpoint.

Expose a single ``GET`` that reports the receiver-specific facts describing the
configured diagnostics-delivery connection, such as an account, a company or a
credential expiry, so an admin can tell a live, correctly-scoped connection from
an expired or misattributed one without opening the receiver's own console.
Which facts exist and what they are called is declared by the delivery plan's
own connection-details step, so nothing here names a receiver's field: the plan
declares, this route serves, and its caller renders.

Every outcome is answered with HTTP 200. A deployment that declares no such
step, stored inputs that no longer fit the plan, a refused credential and an
unreachable receiver are all states a panel renders rather than errors a caller
handles, so the discriminator carries the distinction and the status code does
not. *Why* a fetch failed stays with the connectivity check, which already
classifies delivery failures against the same receiver; this route reports only
that it did.

The route branches on the resolution's code rather than on its plan, so the
unavailable outcomes map through one table. That branch narrows nothing for a
type checker, so the ``plan is None`` arm is what narrows the optional; the
resolution's own exactly-one invariant is what makes that arm unreachable.

The router registers ``IsApiAdmin`` alone, where its admin siblings register the
bearer gate for unsafe methods beside it: this router declares only a ``GET``,
the parent already carries that dependency, and repeating it would add an inert
entry to the generated schema. A router that later declares an unsafe method
needs it added.

Nothing caps the answer. How many pairs come back is bounded by the plan's own
``details`` declaration rather than by anything the receiver controls, so the
receiver cannot lengthen the list; the length of each individual value is
whatever it put at that pointer, and no truncation is applied.

The failure log names the exception's type rather than rendering the exception,
and carries no traceback. ``RemoteAPI`` maps an upstream error body's ``detail``
onto the exception it raises, so rendering that exception would put a
receiver-supplied value into the log that the withheld response body is kept out
of. The failure family is what a reader needs here in any case: classifying
*why* a delivery fetch failed belongs to the connectivity check.
"""

import asyncio
import logging
from enum import StrEnum

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.requests.connectivity import EXTERNAL_PROBE_TIMEOUT_SECONDS
from app.sep.bundle_upload.factory import get_delivery_executor
from app.sep.bundle_upload.resolver import (
    DeliveryUnavailableCode,
    resolve_delivery_plan,
)

router = APIRouter()

logger = logging.getLogger(__name__)


class DeliveryConnectionStatusEnum(StrEnum):
    """Enumerate the mutually-exclusive outcomes of a connection-details read."""

    AVAILABLE = "available"
    UNDECLARED = "undeclared"
    NOT_CONFIGURED = "not_configured"
    INPUTS_DRIFTED = "inputs_drifted"
    FETCH_FAILED = "fetch_failed"


class DeliveryConnectionDetail(BaseModel):
    """Report one fact describing the delivery connection.

    :param label: The display label the plan declared, rendered verbatim. A
        machine key would oblige the caller to carry receiver-specific names.
    :param value: The value that label reports.
    """

    label: str
    value: str


class DeliveryConnectionResponse(BaseModel):
    """Report the facts describing the delivery connection, or why there are none.

    :param status: Which of the five outcomes the read reached.
    :param details: The resolved pairs in the plan's declaration order. Empty
        for every status other than ``available``, and empty under ``available``
        when every declared pointer missed, so a caller draws from this alone
        and consults ``status`` only to explain an empty list.
    """

    status: DeliveryConnectionStatusEnum
    details: list[DeliveryConnectionDetail] = []


#: The outcome each unavailability code reports as. Delivery being unconfigured
#: and its stored inputs having drifted stay separate because only the second is
#: fixed by re-supplying the inputs.
_UNAVAILABLE_STATUS: dict[DeliveryUnavailableCode, DeliveryConnectionStatusEnum] = {
    DeliveryUnavailableCode.UNCONFIGURED: DeliveryConnectionStatusEnum.NOT_CONFIGURED,
    DeliveryUnavailableCode.DRIFTED_INPUTS: DeliveryConnectionStatusEnum.INPUTS_DRIFTED,
}


@router.get("/")
async def read_delivery_connection() -> DeliveryConnectionResponse:
    """Report the facts the delivery plan declares about its own connection.

    No way the read can fail reaches the caller as an error: a deployment that
    declares no connection-details step, stored inputs that no longer fit the
    plan, a refused credential, an unreachable receiver and a read that outran
    its bound all answer 200 with the outcome that describes them, so a caller
    renders a state rather than handling an error. The three configuration
    outcomes are decided before any request is issued; the read and the failure
    outcomes are decided only after one.

    :return: The resolved pairs in the plan's declaration order, or the outcome
        explaining why there are none.
    """
    resolution = resolve_delivery_plan()
    if (code := resolution.code) is not None:
        return DeliveryConnectionResponse(status=_UNAVAILABLE_STATUS[code])
    plan = resolution.plan
    if plan is None or plan.connection_details is None:
        return DeliveryConnectionResponse(
            status=DeliveryConnectionStatusEnum.UNDECLARED
        )
    try:
        async with asyncio.timeout(EXTERNAL_PROBE_TIMEOUT_SECONDS):
            async with get_delivery_executor(plan) as executor:
                details = await executor.read_connection_details()
    except Exception as error:  # noqa: BLE001 -- degraded, never surfaced as an error
        logger.warning(
            "Diagnostics delivery connection read failed (%s).",
            type(error).__name__,
        )
        return DeliveryConnectionResponse(
            status=DeliveryConnectionStatusEnum.FETCH_FAILED
        )
    return DeliveryConnectionResponse(
        status=DeliveryConnectionStatusEnum.AVAILABLE,
        details=[
            DeliveryConnectionDetail(label=detail.label, value=detail.value)
            for detail in details
        ],
    )
