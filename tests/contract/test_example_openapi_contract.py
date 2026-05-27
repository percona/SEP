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

"""Reference contract test using Schemathesis against ``inventory_app``.

Demonstrates the canonical pattern for the contract layer in SEP:

- Loads the live ``openapi()`` callable of a mounted app (so plugin-added
  routes are included automatically) and lets Schemathesis derive cases.
- Skips cleanly when ``schemathesis`` is not installed locally so the dev
  loop does not require the contract toolchain to run the unit and
  integration lanes. CI installs ``schemathesis`` and runs the contract
  lane on every PR (milestone M6).

See ``docs/qa-architecture.md`` Section 4.1 and ``docs/testing-guidelines.md``
for the full control contract.
"""

import pytest

schemathesis = pytest.importorskip(
    "schemathesis",
    reason=(
        "schemathesis is not installed locally; contract lane runs in CI. "
        "Install with `pip install schemathesis` to run it on this machine."
    ),
)

from app.inventory.main import inventory_app  # noqa: E402

_schema = schemathesis.from_dict(inventory_app.openapi())


@_schema.parametrize()
def test_inventory_app_conforms_to_its_openapi_schema(case) -> None:
    """Schemathesis-derived cases must satisfy the declared OpenAPI contract.

    The call below uses Schemathesis' built-in default checks: status code,
    content type, schema conformance, headers. The contract lane catches
    drift between what the code implements and what the schema declares —
    especially when plugins add routes dynamically.
    """
    case.call_and_validate()
