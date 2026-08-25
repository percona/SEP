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

import { Route, Routes } from 'react-router';
import { DeliverySetupGate } from './DeliverySetupGate';
import { IncidentListPage } from './IncidentListPage';
import { IncidentWorkspacePage } from './IncidentWorkspacePage';

interface AtwAppProps {
  /** Whether the current user has admin privileges. Pass it from the shell's auth context. */
  isAdmin?: boolean;
}

/**
 * ATW app router. The shell mounts this at ``atw/*``; the incident list is the
 * index route and an incident opens its workspace at ``:incidentId``.
 *
 * Every route ends in an upload to a ServiceNow case, so the whole router sits
 * behind {@link DeliverySetupGate}: the gate belongs to the app rather than to
 * the shell, which keeps the shell free of app-specific settings knowledge and
 * lets the gate travel with this package.
 */
export function AtwApp({ isAdmin = false }: AtwAppProps) {
  return (
    <DeliverySetupGate isAdmin={isAdmin}>
      <Routes>
        <Route index element={<IncidentListPage />} />
        <Route path=":incidentId" element={<IncidentWorkspacePage />} />
      </Routes>
    </DeliverySetupGate>
  );
}
