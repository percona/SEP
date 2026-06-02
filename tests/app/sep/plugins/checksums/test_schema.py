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

"""Unit tests for the checksums plugin schema declaration."""

from fastapi import status
from fastapi.testclient import TestClient

from app.sep.plugins.checksums.schema import checksums_schema


def test_checksums_schema_has_stats_capability_true():
    """Checksums opts into the aggregated stats card capability."""
    assert checksums_schema.capabilities is not None
    assert checksums_schema.capabilities.stats is True


def test_checksums_schema_other_capabilities_unchanged():
    """Adding ``pii_anonymization`` must not regress the existing capability flags."""
    caps = checksums_schema.capabilities
    assert caps is not None
    assert caps.chaining is True
    assert caps.alert_on_fail is True
    assert caps.scheduling is True
    assert caps.stats is True


def test_checksums_schema_has_pii_anonymization_capability_true():
    """Checksums opts into the PII anonymization detail section capability."""
    assert checksums_schema.capabilities is not None
    assert checksums_schema.capabilities.pii_anonymization is True


def test_checksums_schema_endpoint_exposes_pii_anonymization_capability(
    test_client: TestClient,
) -> None:
    """The plugin-schema API surface must expose ``pii_anonymization=True`` for checksums."""
    response = test_client.get("/api/plugins/checksums/schema")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["capabilities"]["pii_anonymization"] is True


def test_checksums_schema_endpoint_exposes_stats_capability(
    test_client: TestClient,
) -> None:
    """The plugin-schema API surface must expose ``stats=True`` for checksums."""
    response = test_client.get("/api/plugins/checksums/schema")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["capabilities"]["stats"] is True
