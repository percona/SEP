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

import { Navigate, useLocation } from 'react-router';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import { useAuth } from '../contexts/auth';

/**
 * Wraps authenticated routes. Shows a loading spinner during session
 * bootstrap, then redirects to /login if the user is not authenticated.
 */
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, ready, loading } = useAuth();
  const location = useLocation();

  // Session bootstrap still running — show loading
  if (!ready || loading) {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

  // Not authenticated — redirect to login with return URL
  if (!isAuthenticated) {
    const returnUrl = location.pathname + location.search + location.hash;
    return <Navigate to={`/login?redirect=${encodeURIComponent(returnUrl)}`} replace />;
  }

  return <>{children}</>;
}
