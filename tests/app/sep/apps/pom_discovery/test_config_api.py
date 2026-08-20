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

"""Test the app's own ``/config``, and the two decisions that put it there.

The app serves its configuration rather than pointing callers at
``/api/sep/admin/settings`` because that router is admin-gated and **PMM's principal
is not an admin**: ``--sep-token`` resolves to the synthetic ``sep-service`` user,
built with ``is_admin=False`` on purpose since it is a deployment-level shared secret
with nobody behind it. That is asserted here rather than described, because it is the
whole reason this endpoint exists and a later change making the principal an admin
would silently remove the reason.

The second decision is ``CREDENTIALS_PATH`` staying cold. It names a file the payload
reads on every database *host* and hands to a driver as a URI, so an overridable one
would turn "configure this app" into "read a chosen file across the estate". A test
asserts it is refused, because the difference between "not hot" and "not yet hot" is
invisible in the field list.
"""

import pytest
import pytest_asyncio
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import _SERVICE_PRINCIPAL
from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.registry import hot_field_names
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.apps.pom_discovery.config import (
    pom_discovery_settings,
    PomDiscoverySettings,
)
from app.sep.deps import (
    get_current_user,
    get_session,
    require_bearer_for_unsafe_methods,
)
from app.sep.main import build_sep_override_callbacks, sep_app

BASE = "/api/apps/pom_discovery"

#: The YAML-configured values these tests assert against, taken from the class so a
#: default change moves the assertions with it rather than silently passing.
DEFAULTS = PomDiscoverySettings()


@pytest_asyncio.fixture
async def api(regular_user: CasdoorUser, session: AsyncSession) -> AsyncClient:
    """Yield an authenticated client sharing the test session.

    :param regular_user: The authenticated user.
    :param session: The database session the routes should use.
    :return: The client.
    """
    sep_app.dependency_overrides[require_bearer_for_unsafe_methods] = lambda: None
    sep_app.dependency_overrides[get_current_user] = lambda: regular_user
    sep_app.dependency_overrides[get_session] = lambda: session
    client = AsyncClient(
        transport=ASGITransport(app=sep_app),
        base_url="http://test",
        headers={"Authorization": "Bearer test"},
    )
    try:
        yield client
    finally:
        await client.aclose()
        sep_app.dependency_overrides = {}


@pytest.fixture(autouse=True)
def _reset_proxy_snapshot() -> None:
    """Drop any snapshot a test published, so the next test starts from YAML.

    The proxy is a module singleton shared across the whole session; a test that
    publishes an override would otherwise leak a 60-second schedule into every test
    that reads the setting afterwards.
    """
    yield
    pom_discovery_settings._set_snapshot({})


class TestWhyThisEndpointExists:
    """Assert the premise: the settings router is closed to PMM's principal."""

    def test_the_sep_token_principal_is_not_an_admin(self) -> None:
        """``--sep-token`` cannot reach ``/api/sep/admin/settings``.

        Not a statement about the current deployment's configuration -- the service
        principal is constructed in code with no ``is_admin`` argument, so this holds
        in every deployment. If it ever stops holding, the argument for an app-owned
        ``/config`` weakens and this test is where that gets noticed.
        """
        assert _SERVICE_PRINCIPAL.is_admin is False


class TestTheAppIsActuallyWiredIn:
    """Assert the registration a unit test of the endpoint cannot see.

    ``/config`` answers correctly with none of this in place: ``GET`` reads override
    rows straight from the database, and ``PATCH`` republishes the proxy snapshot
    inline, so a request appears to work end to end. What breaks is the *next
    process*: without the collection below the refresher never republishes, and an
    override silently reverts to YAML on restart. Measured happening in the sandbox --
    a 25-minute sweep that went back to 10 after ``./om restart sep-backend``.
    """

    def test_the_declaration_is_reachable_from_the_package(self) -> None:
        """``APP_OWNED_SETTINGS_CLASSES`` must be re-exported from ``__init__``.

        The collector does ``getattr(import_module(plugin.module_name), ...)`` against
        the app *package*, so a declaration that only exists in
        ``app_owned_settings.py`` is never found.
        """
        entries = collect_app_owned_settings_classes()

        assert SettingClassEnum.POM_DISCOVERY_SETTINGS in {
            entry.setting_class for entry in entries
        }

    def test_a_schedule_change_re_seeds_the_beat_row(self) -> None:
        """``SCHEDULE`` must be wired to the beat re-seed callback.

        The proxy holding a new interval is not the same thing as beat running on it:
        beat reads ``celery_periodictask``, which only changes when
        ``_reseed_system_periodic_tasks`` runs. Without this entry a schedule change
        is visible over the API and has no effect on when the sweep actually fires --
        the worst shape a configuration bug can take.
        """
        callbacks = build_sep_override_callbacks(sep_app)

        assert (
            SettingClassEnum.POM_DISCOVERY_SETTINGS,
            "SCHEDULE",
        ) in callbacks


class TestGetConfig:
    """Read the app's configuration."""

    @pytest.mark.asyncio
    async def test_lists_every_field_not_only_overridden_ones(
        self, api: AsyncClient
    ) -> None:
        """Every field is listed, so "why is it sweeping every 10 minutes" is answerable.

        :param api: The authenticated client.
        """
        response = await api.get(f"{BASE}/config")

        assert response.status_code == status.HTTP_200_OK
        keys = {row["key"] for row in response.json()}
        scalars = set(PomDiscoverySettings.model_fields) - {"SCHEDULE"}
        assert scalars <= keys

    @pytest.mark.asyncio
    async def test_the_schedule_is_listed_as_leaves_not_as_one_object(
        self, api: AsyncClient
    ) -> None:
        """``SCHEDULE`` arrives split into ``SCHEDULE__every`` / ``SCHEDULE__period``.

        The LIST projection expands any nested-model field into its leaves, so a
        caller reading ``/config`` never sees a key literally named ``SCHEDULE`` --
        the same shape the ``alerts`` app's ``BACKUP_INTERVAL`` produces. Asserted
        because ``PATCH`` accepts *both* spellings (see below) and a reader who
        assumes GET and PATCH share one key set will build a form against a key that
        is not there.

        :param api: The authenticated client.
        """
        rows = {row["key"]: row for row in (await api.get(f"{BASE}/config")).json()}

        assert "SCHEDULE" not in rows
        assert rows["SCHEDULE__every"]["value"] == DEFAULTS.SCHEDULE.every
        assert rows["SCHEDULE__period"]["value"] == "minutes"
        assert rows["SCHEDULE__every"]["has_override"] is False


class TestPatchConfig:
    """Change the app's configuration at runtime."""

    @pytest.mark.asyncio
    async def test_a_schedule_change_takes_effect_on_the_proxy(
        self, api: AsyncClient
    ) -> None:
        """A PATCH is visible through the settings proxy without a restart.

        The point of the whole registration: the running process reads the new value
        immediately, because the handler republishes the snapshot inline rather than
        waiting for the background refresher.

        :param api: The authenticated client.
        """
        response = await api.patch(
            f"{BASE}/config", json={"SCHEDULE": {"every": 2, "period": "minutes"}}
        )

        assert response.status_code == status.HTTP_200_OK
        assert pom_discovery_settings.SCHEDULE.every == 2  # noqa: PLR2004

    @pytest.mark.asyncio
    async def test_a_single_schedule_leaf_can_be_changed_on_its_own(
        self, api: AsyncClient
    ) -> None:
        """The leaf spelling GET returns is also accepted by PATCH.

        Both forms work, and the asymmetry runs the other way: only the whole-object
        form can express ``null``. A UI driven off the GET key set therefore needs the
        parent key too, which is the one thing it cannot discover from GET.

        :param api: The authenticated client.
        """
        response = await api.patch(f"{BASE}/config", json={"SCHEDULE__every": 30})

        assert response.status_code == status.HTTP_200_OK
        assert pom_discovery_settings.SCHEDULE.every == 30  # noqa: PLR2004
        assert pom_discovery_settings.SCHEDULE.period == "minutes", (
            "changing one leaf must not reset the other to its default"
        )

    @pytest.mark.asyncio
    async def test_a_null_schedule_unregisters_the_sweep(
        self, api: AsyncClient
    ) -> None:
        """``SCHEDULE: null`` is a legitimate value, not a missing one.

        It is how an operator says "trigger only", and a nullable union is exactly the
        shape a coercion layer is most likely to mishandle -- so it is asserted rather
        than assumed to fall out of the type.

        :param api: The authenticated client.
        """
        response = await api.patch(f"{BASE}/config", json={"SCHEDULE": None})

        assert response.status_code == status.HTTP_200_OK
        assert pom_discovery_settings.SCHEDULE is None

    @pytest.mark.asyncio
    async def test_a_change_is_persisted_as_an_override_row(
        self, api: AsyncClient, session: AsyncSession
    ) -> None:
        """The change survives the process, which is what makes it configuration.

        :param api: The authenticated client.
        :param session: The database session.
        """
        await api.patch(f"{BASE}/config", json={"RUN_RETENTION": 5})

        rows = await SettingsOverrideManager.list(
            session,
            setting_class=SettingClassEnum.POM_DISCOVERY_SETTINGS,
            is_active=True,
        )
        assert [(row.key, row.value) for row in rows] == [("RUN_RETENTION", 5)]

    @pytest.mark.asyncio
    async def test_a_bad_value_is_refused_by_the_field_constraint(
        self, api: AsyncClient
    ) -> None:
        """``PositiveInt`` is enforced on the way in, not at the next sweep.

        A zero here would make ``MAX_CONCURRENT_PROBES`` a semaphore that never admits
        anyone, and the sweep would hang rather than fail.

        :param api: The authenticated client.
        """
        response = await api.patch(f"{BASE}/config", json={"MAX_CONCURRENT_PROBES": 0})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert (
            pom_discovery_settings.MAX_CONCURRENT_PROBES
            == DEFAULTS.MAX_CONCURRENT_PROBES
        )

    @pytest.mark.asyncio
    async def test_one_bad_key_rejects_the_whole_batch(self, api: AsyncClient) -> None:
        """Nothing is written when any key fails, so no partial apply is reachable.

        :param api: The authenticated client.
        """
        response = await api.patch(
            f"{BASE}/config", json={"RUN_RETENTION": 5, "POLL_INTERVAL": -1}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert pom_discovery_settings.RUN_RETENTION == DEFAULTS.RUN_RETENTION

    @pytest.mark.asyncio
    async def test_credentials_path_is_not_settable(self, api: AsyncClient) -> None:
        """A cold field is refused, not silently ignored.

        ``CREDENTIALS_PATH`` names a file read on every database host and handed to a
        driver as a URI. Overridable, it would widen "configure this app" into "read a
        chosen file across the estate", so it stays YAML/env only.

        :param api: The authenticated client.
        """
        response = await api.patch(
            f"{BASE}/config", json={"CREDENTIALS_PATH": "/etc/passwd"}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "CREDENTIALS_PATH" not in hot_field_names(PomDiscoverySettings)

    @pytest.mark.asyncio
    async def test_an_override_can_be_cleared_back_to_the_deployment_value(
        self, api: AsyncClient, session: AsyncSession
    ) -> None:
        """DELETE restores the YAML value, so "no override" stays reachable.

        Without it an operator who changed a value once can only ever change it to
        another one, and whatever the deployment ships becomes unrecoverable through
        the API.

        :param api: The authenticated client.
        :param session: The database session.
        """
        await api.patch(f"{BASE}/config", json={"RUN_RETENTION": 5})

        response = await api.delete(f"{BASE}/config/RUN_RETENTION")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert pom_discovery_settings.RUN_RETENTION == DEFAULTS.RUN_RETENTION
        assert not await SettingsOverrideManager.list(
            session,
            setting_class=SettingClassEnum.POM_DISCOVERY_SETTINGS,
            is_active=True,
        )

    @pytest.mark.asyncio
    async def test_clearing_a_field_that_was_never_set_is_not_an_error(
        self, api: AsyncClient
    ) -> None:
        """DELETE is idempotent, so a revert-everything sweep needs no bookkeeping.

        :param api: The authenticated client.
        """
        response = await api.delete(f"{BASE}/config/RUN_RETENTION")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_an_unknown_key_is_refused(self, api: AsyncClient) -> None:
        """A typo does not become a stored row nobody reads.

        :param api: The authenticated client.
        """
        response = await api.patch(f"{BASE}/config", json={"SCHEDUEL": 1})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
