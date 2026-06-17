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

/**
 * Splash shown by `AppDisabledGuard` in place of a disabled app's route.
 *
 * Generic by design: it surfaces neither the disable reason nor the admin
 * contact (deferred to a future ticket once the backend exposes that
 * metadata). Built on the shared `CenteredSplash` layout, like `NotFoundPage`.
 */
export default function AppDisabledPage() {
  return (
    <CenteredSplash
      icon={<BlockIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />}
      title="This feature is currently disabled."
      body="Contact an administrator to re-enable it."
    />
  );
}
