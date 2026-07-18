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

"""Define tests for the app.core.celery.config module."""

import pytest
from pydantic import ValidationError

from app.core.celery.config import CeleryOptions

_BROKER_URL = "redis://localhost:6379/0"


def test_beat_engine_options_defaults_to_empty_dict():
    """Confirm beat_engine_options is empty for a standalone deployment."""
    options = CeleryOptions(broker_url=_BROKER_URL)

    assert options.beat_engine_options == {}


def test_beat_engine_options_round_trip_through_model_dump():
    """Confirm the pool dict reaches the Celery-conf surface intact via model_dump()."""
    pool = {"pool_size": 20, "max_overflow": 5, "pool_timeout": 30}
    options = CeleryOptions(broker_url=_BROKER_URL, beat_engine_options=pool)

    assert options.model_dump()["beat_engine_options"] == pool


def test_beat_engine_options_accepts_zero_max_overflow():
    """Accept max_overflow=0 (no overflow) for the side-car cap."""
    options = CeleryOptions(
        broker_url=_BROKER_URL, beat_engine_options={"max_overflow": 0}
    )

    assert options.beat_engine_options == {"max_overflow": 0}


@pytest.mark.parametrize(
    "pool",
    [
        {"poolsize": 1},
        {"pool_size": 0},
        {"max_overflow": -1},
        {"pool_timeout": 0},
    ],
)
def test_beat_engine_options_rejects_invalid_values(pool):
    """Reject unknown keys and out-of-range values at config load."""
    with pytest.raises(ValidationError):
        CeleryOptions(broker_url=_BROKER_URL, beat_engine_options=pool)
