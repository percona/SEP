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

"""Resolve the effective delivery plan from the baked skeleton and its inputs.

This module must stay out of ``app/sep/bundle_upload/__init__.py``:
``app.sep.config`` imports :class:`~app.sep.bundle_upload.plan.DeliveryPlan` from
this package, so the package ``__init__`` executes while ``app.sep.config`` is
still running its own module body, and importing ``sep_settings`` from there
would fail. Import this module directly instead, as ``app.sep.apps.atw.send``
already does for ``factory``.
"""

import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.utils import deep_dict_update
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.config import sep_settings

__all__ = [
    "DRIFTED_INPUTS_REASON",
    "UNCONFIGURED_REASON",
    "DeliveryPlanResolution",
    "resolve_delivery_plan",
]

logger = logging.getLogger(__name__)

#: Reported when this deployment has no usable receiver at all: no baked plan,
#: or a declared secret still without a value. The operator has to configure
#: delivery.
UNCONFIGURED_REASON = "Diagnostics delivery is not configured"

#: Reported when delivery *was* configured and the inputs have since stopped
#: fitting the plan, which an image upgrade renaming a declared secret produces.
#: The operator has to re-supply the inputs, so this may not read as the
#: never-configured state. It names no secret: those are the receiver's own
#: internal field names, which the operator cannot act on.
DRIFTED_INPUTS_REASON = (
    "The stored diagnostics delivery inputs no longer match this deployment's "
    "delivery plan; re-supply them."
)


@dataclass(frozen=True, slots=True)
class DeliveryPlanResolution:
    """Report the effective delivery plan, or why there is not one.

    Exactly one member is set. The reason exists because three distinct causes
    — no baked plan, a declared secret left empty, and inputs that no longer
    fit the plan — would otherwise collapse into one indistinguishable "not
    configured", and the last of them calls for a different action from the
    other two.

    Build one through :meth:`resolved` or :meth:`unavailable` rather than the
    constructor, which states the same invariant but only as a runtime refusal.

    :param plan: The plan to deliver with, or ``None`` when there is none.
    :param reason: The operator-facing reason there is no plan, or ``None``
        when there is one. Never names a secret the plan declares.
    """

    plan: DeliveryPlan | None
    reason: str | None

    def __post_init__(self) -> None:
        """Refuse a resolution that carries both outcomes, or neither.

        Callers read one member off the other's emptiness, so an instance
        holding neither would report a deployment as able to deliver with no
        plan to deliver by.

        :raises ValueError: When both members are set, or neither is.
        """
        if (self.plan is None) == (self.reason is None):
            raise ValueError(
                "A delivery plan resolution carries either a plan or a reason "
                "for there being none, not both and not neither."
            )

    @classmethod
    def resolved(cls, plan: DeliveryPlan) -> "DeliveryPlanResolution":
        """Return the resolution for a deployment that can deliver.

        :param plan: The plan to deliver with.
        :return: The resolution carrying it.
        """
        return cls(plan=plan, reason=None)

    @classmethod
    def unavailable(cls, reason: str) -> "DeliveryPlanResolution":
        """Return the resolution for a deployment that cannot deliver.

        :param reason: The operator-facing reason, from this module's constants.
        :return: The resolution carrying it.
        """
        return cls(plan=None, reason=reason)


def resolve_delivery_plan() -> DeliveryPlanResolution:
    """Return the effective delivery plan, or the reason there is none.

    Merge ``DIAGNOSTICS_DELIVERY_INPUTS`` onto the baked
    ``DIAGNOSTICS_DELIVERY`` skeleton and rebuild the result through
    :class:`~app.sep.bundle_upload.plan.DeliveryPlan` validation, so a merged
    plan has passed the same cross-reference checks a file-configured one does.
    Both settings are read on every call, since an override that landed after
    import must take effect.

    Every unconfigured and every invalid case resolves to a reason rather than
    raising, so a caller rendering UI state from this value never fails merely
    because delivery is unconfigured or misconfigured.

    Inputs naming a secret the skeleton does not declare are reported as drift,
    which is what an image upgrade renaming a declared secret leaves behind.
    Both routes an inputs value can arrive by reach this one check: a stored
    override row survives snapshot build unfiltered (see
    :func:`~app.sep.config.materialize_delivery_plan_inputs`), and a YAML- or
    environment-set value never passed a name check at all.

    The check is deliberately one-directional, and so deliberately narrower than
    the exact-match rule :func:`~app.sep.config.materialize_delivery_plan_inputs`
    enforces on write. An undeclared name is a dangling reference: nothing reads
    the value, and only re-supplying the inputs clears it. A declared name the
    inputs omit is not, because the merge below falls back to the skeleton's own
    value — which either delivers or reports itself empty, and both of those are
    already the right answer for an operator who has one more secret to supply.
    Write-time is stricter for a reason of its own: a whole-object PATCH that
    silently left some secrets on baked values would surprise whoever submitted
    it, not because a partial stored row is unreadable.

    Check order carries meaning. A deployment with no baked plan is
    unconfigured, never drifted — there is nothing to have drifted from. Drift
    is then decided before the empty-value check, because a rename produces both
    symptoms and only the rename is actionable.

    :return: The resolved plan, or the reason delivery is unavailable.
    """
    skeleton = sep_settings.DIAGNOSTICS_DELIVERY
    if skeleton is None:
        return DeliveryPlanResolution.unavailable(UNCONFIGURED_REASON)

    inputs = sep_settings.DIAGNOSTICS_DELIVERY_INPUTS
    secrets = dict(skeleton.secrets)
    if inputs is not None:
        if undeclared := sorted(set(inputs.secrets) - set(skeleton.secrets)):
            logger.warning(
                "Diagnostics delivery inputs name secret(s) %s, which this "
                "deployment's plan does not declare; treating the stored inputs "
                "as drifted.",
                ", ".join(undeclared),
            )
            return DeliveryPlanResolution.unavailable(DRIFTED_INPUTS_REASON)
        secrets.update(inputs.secrets)
    if empty := sorted(
        name for name, secret in secrets.items() if not secret.get_secret_value()
    ):
        logger.info(
            "Diagnostics delivery has no value for secret(s) %s; treating it as "
            "unconfigured.",
            ", ".join(empty),
        )
        return DeliveryPlanResolution.unavailable(UNCONFIGURED_REASON)
    if inputs is None:
        return DeliveryPlanResolution.resolved(skeleton)

    data = skeleton.model_dump()
    overlay = (
        {"secrets": secrets}
        if inputs.endpoint is None
        else {"secrets": secrets, "endpoint": inputs.endpoint}
    )
    deep_dict_update(data, overlay)
    try:
        plan = DeliveryPlan.model_validate(data)
    except ValidationError as exc:
        logger.warning("Diagnostics delivery inputs produce an invalid plan: %s", exc)
        return DeliveryPlanResolution.unavailable(UNCONFIGURED_REASON)
    return DeliveryPlanResolution.resolved(plan)
