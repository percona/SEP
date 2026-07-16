/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import BlockIcon from '@mui/icons-material/Block';
import CenteredSplash from '../components/CenteredSplash';

interface AppDisabledPageProps {
  /** Display name of the disabled app; names the feature in the title. */
  appDisplayName?: string;
  /**
   * Display names of the required apps whose being off blocks this app. When
   * non-empty the splash names them; otherwise it shows the generic copy.
   */
  blockingDependencyNames?: string[];
}

/** Build the splash body naming the required app(s) an admin must enable. */
function dependencyMessage(names: string[]): string {
  if (names.length === 1) {
    return `The ${names[0]} app must be enabled first. Contact an administrator to enable it.`;
  }
  return `These apps must be enabled first: ${names.join(', ')}. Contact an administrator to enable them.`;
}

/**
 * Render the disabled-app splash for `AppDisabledGuard` in place of the route.
 *
 * When the disablement is dependency-driven — the app's own state is enabled
 * but a required app is off — the title names the unavailable feature and the
 * body names the required app(s) to enable, so the blocking dependency is the
 * first thing the user reads. When the app is disabled by its own state (or no
 * blocking dependency is supplied), fall back to the generic copy. Built on the
 * shared `CenteredSplash` layout, like `NotFoundPage`.
 */
export default function AppDisabledPage({
  appDisplayName,
  blockingDependencyNames = [],
}: AppDisabledPageProps) {
  const isDependencyDriven = blockingDependencyNames.length > 0;
  return (
    <CenteredSplash
      icon={<BlockIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />}
      title={
        isDependencyDriven
          ? `${appDisplayName || 'This feature'} is unavailable`
          : 'This feature is currently disabled.'
      }
      body={
        isDependencyDriven
          ? dependencyMessage(blockingDependencyNames)
          : 'Contact an administrator to re-enable it.'
      }
    />
  );
}
