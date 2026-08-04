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

from pydantic import ValidationError

from app.core.utils import deep_dict_update
from app.sep.bundle_upload.plan import DeliveryPlan
from app.sep.config import sep_settings

__all__ = ["resolve_delivery_plan"]

logger = logging.getLogger(__name__)


def resolve_delivery_plan() -> DeliveryPlan | None:
    """Return the effective delivery plan, or ``None`` when unconfigured.

    Merge ``DIAGNOSTICS_DELIVERY_INPUTS`` onto the baked
    ``DIAGNOSTICS_DELIVERY`` skeleton and rebuild the result through
    :class:`~app.sep.bundle_upload.plan.DeliveryPlan` validation, so a merged
    plan has passed the same cross-reference checks a file-configured one does.
    Both settings are read on every call, since an override that landed after
    import must take effect.

    Every unconfigured and every invalid case resolves to ``None`` rather than
    raising: ``diagnostics_send_disabled_reasons`` calls this while rendering the
    send action, so an exception here would fail that request.

    A stored inputs override whose secret names stop matching the skeleton --
    after an image upgrade renames one -- is dropped from the settings snapshot
    with a warning rather than surfaced as an error, so delivery degrades to
    unconfigured instead of failing the read.

    :return: The plan to deliver with, or ``None`` when delivery is not
        configured.
    """
    skeleton = sep_settings.DIAGNOSTICS_DELIVERY
    if skeleton is None:
        return None

    inputs = sep_settings.DIAGNOSTICS_DELIVERY_INPUTS
    secrets = dict(skeleton.secrets)
    if inputs is not None:
        secrets.update(
            {
                name: value
                for name, value in inputs.secrets.items()
                if name in skeleton.secrets
            }
        )
    if empty := sorted(
        name for name, secret in secrets.items() if not secret.get_secret_value()
    ):
        logger.info(
            "Diagnostics delivery has no value for secret(s) %s; treating it as "
            "unconfigured.",
            ", ".join(empty),
        )
        return None
    if inputs is None:
        return skeleton

    data = skeleton.model_dump()
    overlay = (
        {"secrets": secrets}
        if inputs.endpoint is None
        else {"secrets": secrets, "endpoint": inputs.endpoint}
    )
    deep_dict_update(data, overlay)
    try:
        return DeliveryPlan.model_validate(data)
    except ValidationError as exc:
        logger.warning("Diagnostics delivery inputs produce an invalid plan: %s", exc)
        return None
