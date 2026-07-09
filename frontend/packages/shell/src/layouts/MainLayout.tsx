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
import Toolbar from '@mui/material/Toolbar';
import Container from '@mui/material/Container';
import { Outlet } from 'react-router-dom';
import { NavigationProvider } from '../contexts/navigation';
import TheHeader from './TheHeader';
import TheSidebar from './TheSidebar';

export default function MainLayout() {
  return (
    <NavigationProvider>
      <Box sx={{ display: 'flex', minHeight: '100vh' }}>
        <TheHeader />
        <TheSidebar />
        <Box component="main" sx={{ flexGrow: 1, minWidth: 0 }}>
          <Toolbar /> {/* spacer for AppBar */}
          <Container maxWidth={false} sx={{ py: 3 }}>
            <Outlet />
          </Container>
        </Box>
      </Box>
    </NavigationProvider>
  );
}
