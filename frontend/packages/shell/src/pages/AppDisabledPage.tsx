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
  /** Display name of the disabled app; used only for the dependency message. */
  appDisplayName?: string;
  /**
   * Display names of the required apps whose being off blocks this app. When
   * non-empty the splash names them; otherwise it shows the generic copy.
   */
  blockingDependencyNames?: string[];
}

/** Build the dependency-driven splash body naming the required app(s). */
function dependencyMessage(appDisplayName: string | undefined, names: string[]): string {
  const app = appDisplayName ?? 'This app';
  if (names.length === 1) {
    return `${app} requires the ${names[0]} app, which is currently disabled.`;
  }
  return `${app} requires these apps, which are currently disabled: ${names.join(', ')}.`;
}

/**
 * Render the disabled-app splash for `AppDisabledGuard` in place of the route.
 *
 * When the disablement is dependency-driven — the app's own state is enabled
 * but a required app is off — name the blocking app(s). When the app is disabled
 * by its own state (or no blocking dependency is supplied), fall back to the
 * generic copy. Built on the shared `CenteredSplash` layout, like `NotFoundPage`.
 */
export default function AppDisabledPage({
  appDisplayName,
  blockingDependencyNames = [],
}: AppDisabledPageProps = {}) {
  const isDependencyDriven = blockingDependencyNames.length > 0;
  return (
    <CenteredSplash
      icon={<BlockIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />}
      title="This feature is currently disabled."
      body={
        isDependencyDriven
          ? dependencyMessage(appDisplayName, blockingDependencyNames)
          : 'Contact an administrator to re-enable it.'
      }
    />
  );
}
