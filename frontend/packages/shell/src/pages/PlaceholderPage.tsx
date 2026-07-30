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

import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ConstructionIcon from '@mui/icons-material/Construction';
import { useLocation } from 'react-router';
import { useNotification } from '../contexts/notification';

export default function PlaceholderPage() {
  const location = useLocation();
  const { showSuccess, showError, showWarning, showInfo } = useNotification();

  // Derive page title from the URL path
  const title = location.pathname
    .split('/')
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' / ');

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 10,
        textAlign: 'center',
      }}
    >
      <ConstructionIcon sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
      <Typography variant="h5" gutterBottom>
        {title || 'Page'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
        This section will be implemented during the frontend migration.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', justifyContent: 'center' }}>
        <Button variant="contained" onClick={() => showSuccess('Success toast')}>
          Show Success
        </Button>
        <Button variant="contained" onClick={() => showError('Error toast')}>
          Show Error
        </Button>
        <Button variant="contained" onClick={() => showWarning('Warning toast')}>
          Show Warning
        </Button>
        <Button variant="contained" onClick={() => showInfo('Info toast')}>
          Show Info
        </Button>
      </Stack>
    </Box>
  );
}
