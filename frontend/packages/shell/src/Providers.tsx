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

import { Suspense, type ReactNode } from 'react';
import CircularProgress from '@mui/material/CircularProgress';
import Box from '@mui/material/Box';
import { AuthProvider } from './contexts/auth';
import { NotificationProvider } from './contexts/notification';

function LoadingFallback() {
  return (
    <Box
      sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '100vh' }}
    >
      <CircularProgress />
    </Box>
  );
}

export default function Providers({ children }: { children: ReactNode }) {
  return (
    <NotificationProvider>
      <AuthProvider>
        <Suspense fallback={<LoadingFallback />}>{children}</Suspense>
      </AuthProvider>
    </NotificationProvider>
  );
}
