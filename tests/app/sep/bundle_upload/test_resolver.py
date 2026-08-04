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

"""Define tests for the effective-delivery-plan resolver."""

import logging

import pytest
from pytest_mock import MockerFixture

from app.sep.bundle_upload.plan import DeliveryPlan, UploadStep
from app.sep.bundle_upload.resolver import resolve_delivery_plan
from app.sep.config import DeliveryPlanInputs, sep_settings

_BAKED_ENDPOINT = "https://intake.example.com/"


def _plan(secrets: dict[str, str], *, endpoint: str = _BAKED_ENDPOINT) -> DeliveryPlan:
    """Build a plan whose upload cites every secret name it declares.

    :param secrets: The secret names and values the plan declares.
    :param endpoint: The receiver base URL.
    :return: The validated plan.
    """
    return DeliveryPlan(
        endpoint=endpoint,
        secrets=secrets,
        upload={
            "path": "attachment/upload",
            "headers": {
                f"x-{name}": {"source": "secret", "name": name} for name in secrets
            },
            "reference_pointer": "/result/sys_id",
        },
    )


@pytest.fixture(name="no_inputs")
def no_inputs_fixture(mocker: MockerFixture) -> None:
    """Leave the runtime inputs unset, as a deployment that never PATCHed them."""
    mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY_INPUTS", None)


@pytest.mark.usefixtures("no_inputs")
class TestSkeletonOnly:
    """Cover the resolver's behaviour when no runtime inputs are supplied."""

    def test_returns_none_without_a_baked_plan(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Report the ordinary unconfigured state silently, without a log line."""
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", None)

        with caplog.at_level(logging.INFO):
            assert resolve_delivery_plan() is None

        assert caplog.records == []

    def test_returns_the_baked_plan_unchanged(self, mocker: MockerFixture) -> None:
        """Hand back a fully-configured skeleton as-is for a standalone deployment."""
        skeleton = _plan({"api_key": "real-api-key"})
        mocker.patch.object(sep_settings, "DIAGNOSTICS_DELIVERY", skeleton)

        assert resolve_delivery_plan() is skeleton

    def test_reports_every_declared_secret_left_empty(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Refuse a plan whose declared secrets have no values, naming each one."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            _plan({"client_token": "", "sn_api_key": ""}),
        )

        with caplog.at_level(logging.INFO):
            assert resolve_delivery_plan() is None

        assert "client_token, sn_api_key" in caplog.text


class TestMergedInputs:
    """Cover the merge of runtime inputs onto the baked skeleton."""

    def test_supplied_secrets_reach_the_merged_plan(
        self, mocker: MockerFixture
    ) -> None:
        """Deliver with the values an operator supplied, not the baked blanks."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            _plan({"client_token": "", "sn_api_key": ""}),
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(
                secrets={"client_token": "token-value", "sn_api_key": "key-value"}
            ),
        )

        plan = resolve_delivery_plan()

        assert plan is not None
        assert plan.secrets["sn_api_key"].get_secret_value() == "key-value"
        assert plan.secrets["client_token"].get_secret_value() == "token-value"

    def test_reports_only_the_secret_still_left_empty(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Name just the missing half when the inputs supply one of two secrets."""
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            _plan({"client_token": "", "sn_api_key": ""}),
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(secrets={"sn_api_key": "key-value"}),
        )

        with caplog.at_level(logging.INFO):
            assert resolve_delivery_plan() is None

        assert "client_token" in caplog.text
        assert "sn_api_key" not in caplog.text

    def test_endpoint_input_replaces_the_baked_endpoint(
        self, mocker: MockerFixture
    ) -> None:
        """Point delivery at the receiver an operator named instead of the baked one."""
        mocker.patch.object(
            sep_settings, "DIAGNOSTICS_DELIVERY", _plan({"sn_api_key": ""})
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(
                endpoint="https://elsewhere.example.com/",
                secrets={"sn_api_key": "key-value"},
            ),
        )

        plan = resolve_delivery_plan()

        assert plan is not None
        assert str(plan.endpoint) == "https://elsewhere.example.com/"

    def test_absent_endpoint_input_keeps_the_baked_endpoint(
        self, mocker: MockerFixture
    ) -> None:
        """Keep the baked receiver when the inputs carry secrets only."""
        mocker.patch.object(
            sep_settings, "DIAGNOSTICS_DELIVERY", _plan({"sn_api_key": ""})
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(secrets={"sn_api_key": "key-value"}),
        )

        plan = resolve_delivery_plan()

        assert plan is not None
        assert str(plan.endpoint) == _BAKED_ENDPOINT

    def test_drops_an_input_secret_the_skeleton_does_not_declare(
        self, mocker: MockerFixture
    ) -> None:
        """Ignore an undeclared secret name a YAML- or env-set inputs value carries.

        Such a value never passes ``materialize_delivery_plan_inputs``, which is
        the only exact-key check, so the resolver is what keeps an undeclared
        name out of the merged plan.
        """
        mocker.patch.object(
            sep_settings, "DIAGNOSTICS_DELIVERY", _plan({"sn_api_key": ""})
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(
                secrets={"sn_api_key": "key-value", "rogue": "smuggled"}
            ),
        )

        plan = resolve_delivery_plan()

        assert plan is not None
        assert set(plan.secrets) == {"sn_api_key"}

    def test_returns_none_when_the_merged_plan_fails_validation(
        self, mocker: MockerFixture, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Degrade to unconfigured instead of raising into the request path.

        The skeleton is copied past validation so it cites a secret it never
        declares -- a shape the settings loader rejects but the annotation admits
        -- which is what makes the rebuilt plan fail cross-reference validation.
        """
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY",
            _plan({"sn_api_key": "key-value"}).model_copy(
                update={
                    "upload": UploadStep(
                        path="attachment/upload",
                        headers={
                            "x-client-token": {
                                "source": "secret",
                                "name": "client_token",
                            }
                        },
                    )
                }
            ),
        )
        mocker.patch.object(
            sep_settings,
            "DIAGNOSTICS_DELIVERY_INPUTS",
            DeliveryPlanInputs(secrets={"sn_api_key": "key-value"}),
        )

        with caplog.at_level(logging.WARNING):
            assert resolve_delivery_plan() is None

        assert "client_token" in caplog.text
