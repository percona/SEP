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

import { Route, Routes } from 'react-router-dom';
import { AlertTroubleshootingIndexPage } from './AlertTroubleshootingIndexPage';
import { AlertTroubleshootingDetailPage } from './AlertTroubleshootingDetailPage';

/**
 * Alert Troubleshooting app entry point.
 *
 * Routes:
 *   /alerts/troubleshooting/           → grouped alert browser
 *   /alerts/troubleshooting/:serviceType/:alertName → snippet execution cards
 */
export function AlertTroubleshootingApp() {
  return (
    <Routes>
      <Route index element={<AlertTroubleshootingIndexPage />} />
      <Route path=":serviceType/:alertName" element={<AlertTroubleshootingDetailPage />} />
    </Routes>
  );
}
