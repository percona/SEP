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

"""Look up the :class:`~app.sep.apps.om_bootstrap.strategy.InstallStrategy` for a run.

The one place an :class:`~app.sep.apps.om_bootstrap.strategy.InstallMethod` maps
to a concrete strategy, so ``api_routes.py`` never imports a strategy module
directly -- adding a second strategy (``DockerInstallStrategy``, say) means
adding one module plus one line here, not touching the API layer.
"""

from app.sep.apps.om_bootstrap.strategies.packages import PackagesInstallStrategy
from app.sep.apps.om_bootstrap.strategy import InstallMethod, InstallStrategy

__all__ = ["STRATEGIES", "strategy_for"]

#: Every implemented strategy, keyed by the :class:`InstallMethod` it handles.
#: Only :data:`~app.sep.apps.om_bootstrap.strategy.InstallMethod.PACKAGES` has one
#: today -- ``DOCKER``/``PODMAN`` are declared on the enum for later, not here yet.
STRATEGIES: dict[InstallMethod, InstallStrategy] = {
    InstallMethod.PACKAGES: PackagesInstallStrategy(),
}


def strategy_for(install_method: InstallMethod) -> InstallStrategy:
    """Return the strategy that implements ``install_method``.

    :param install_method: The run's chosen install method.
    :return: The matching strategy.
    :raises ValueError: When no strategy implements ``install_method`` yet.
    """
    try:
        return STRATEGIES[install_method]
    except KeyError:
        raise ValueError(
            f"no InstallStrategy registered for {install_method!r}"
        ) from None
