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

import Typography from '@mui/material/Typography';
import CenteredSplash from '../components/CenteredSplash';

export default function NotFoundPage() {
  return (
    <CenteredSplash
      icon={
        <Typography variant="h1" sx={{ fontWeight: 700, color: 'text.secondary', mb: 1 }}>
          404
        </Typography>
      }
      title="Page not found"
      body="The page you're looking for doesn't exist or has been moved."
    />
  );
}
