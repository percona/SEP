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
import RootLayout from './layouts/RootLayout';
import MainLayout from './layouts/MainLayout';
import AuthGuard from './components/AuthGuard';
import { useAuth } from './contexts/auth';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const PlaceholderPage = lazy(() => import('./pages/PlaceholderPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

// Schema-driven plugins — each is a single lazy import
const ChecksumsPlugin = lazy(() =>
  import('@sep/plugin-checksums').then((m) => ({ default: m.ChecksumsPlugin })),
);
const AtwPlugin = lazy(() => import('@sep/plugin-atw').then((m) => ({ default: m.AtwPlugin })));
const DipperPlugin = lazy(() =>
  import('@sep/plugin-dipper').then((m) => ({ default: m.DipperPlugin })),
);
const InventoryPlugin = lazy(() =>
  import('@sep/inventory').then((m) => ({ default: m.InventoryPlugin })),
);
const SnippetsPluginLazy = lazy(() =>
  import('@sep/plugins-snippets').then((m) => ({ default: m.SnippetsPlugin })),
);
const AlertTroubleshootingPlugin = lazy(() =>
  import('@sep/plugin-alert-troubleshooting').then((m) => ({
    default: m.AlertTroubleshootingPlugin,
  })),
);
const TasksPlugin = lazy(() =>
  import('@sep/plugin-tasks').then((m) => ({ default: m.TasksPlugin })),
);
const ArchivesPlugin = lazy(() =>
  import('@sep/plugin-archives').then((m) => ({ default: m.ArchivesPlugin })),
);

function SnippetsPlugin() {
  const { isAdmin } = useAuth();
  return <SnippetsPluginLazy isAdmin={isAdmin} />;
}

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
          { path: 'inventory/*', element: <InventoryPlugin /> },
          { path: 'tasks/*', element: <TasksPlugin /> },
          { path: 'snippets/*', element: <SnippetsPlugin /> },
          { path: 'atw/*', element: <AtwPlugin /> },
          { path: 'dipper/*', element: <DipperPlugin /> },
          { path: 'alerts/templates', element: <PlaceholderPage /> },
          { path: 'alerts/troubleshooting/*', element: <AlertTroubleshootingPlugin /> },
          { path: 'schema-change/alters', element: <PlaceholderPage /> },
          // Checksums — schema-driven plugin (handles its own sub-routes)
          { path: 'plugins/checksums/*', element: <ChecksumsPlugin /> },
          { path: 'schema-change/checksums/*', element: <ChecksumsPlugin /> },
          { path: 'schema-change/inventory/*', element: <InventoryPlugin /> },
          { path: 'backups/mysql', element: <PlaceholderPage /> },
          { path: 'backups/mongodb', element: <PlaceholderPage /> },
          { path: 'backups/postgresql', element: <PlaceholderPage /> },
          { path: 'plugins/archives/*', element: <ArchivesPlugin /> },
          { path: 'reports', element: <PlaceholderPage /> },
          { path: 'settings', element: <PlaceholderPage /> },
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
