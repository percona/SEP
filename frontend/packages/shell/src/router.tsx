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

import { lazy } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { buildAppRoutes } from './appRegistry';
import RootLayout from './layouts/RootLayout';
import MainLayout from './layouts/MainLayout';
import AuthGuard from './components/AuthGuard';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const AdminAppsPage = lazy(() => import('./pages/AdminAppsPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

const appRoutes = buildAppRoutes();

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      {
        path: '/login',
        element: <LoginPage />,
      },
      {
        path: '/',
        element: (
          <AuthGuard>
            <MainLayout />
          </AuthGuard>
        ),
        children: [
          { index: true, element: <DashboardPage /> },
          ...appRoutes.map(({ path, element }) => ({ path, element })),
          { path: 'settings', element: <SettingsPage /> },
          { path: 'admin/apps', element: <AdminAppsPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
      {
        path: '*',
        element: <Navigate to="/" replace />,
      },
    ],
  },
]);
