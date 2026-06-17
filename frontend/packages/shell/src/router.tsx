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
import AppDisabledGuard from './components/AppDisabledGuard';
import { useAuth } from './contexts/auth';

const DashboardPage = lazy(() => import('./pages/DashboardPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));
const SettingsPage = lazy(() => import('./pages/SettingsPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));

// Schema-driven plugins — each is a single lazy import
const AltersPlugin = lazy(() =>
  import('@sep/plugin-alters').then((m) => ({ default: m.AltersPlugin })),
);
const ChecksumsPlugin = lazy(() =>
  import('@sep/plugin-checksums').then((m) => ({ default: m.ChecksumsPlugin })),
);
const MysqlBackupsPlugin = lazy(() =>
  import('@sep/plugin-mysql-backups').then((m) => ({ default: m.MysqlBackupsPlugin })),
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
const AlertsPlugin = lazy(() =>
  import('@sep/plugin-alerts').then((m) => ({ default: m.AlertsPlugin })),
);
const TasksPlugin = lazy(() =>
  import('@sep/plugin-tasks').then((m) => ({ default: m.TasksPlugin })),
);
const ArchivesPlugin = lazy(() =>
  import('@sep/plugin-archives').then((m) => ({ default: m.ArchivesPlugin })),
);
const BackupMongoPlugin = lazy(() =>
  import('@sep/plugin-backup-mongo').then((m) => ({ default: m.BackupMongoPlugin })),
);
const BackupPgPlugin = lazy(() =>
  import('@sep/plugin-backup-pg').then((m) => ({ default: m.BackupPgPlugin })),
);
const ReportPlugin = lazy(() =>
  import('@sep/plugin-report').then((m) => ({ default: m.ReportPlugin })),
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
          // The Inventory app is not gated by plugin enablement (protected app)
          // — it stays unwrapped. Every other plugin route is wrapped in an
          // AppDisabledGuard tagged with the backend plugin key, so navigating
          // to a disabled app's route lands on the splash instead of mounting a
          // plugin that would emit a 503 toast cascade. Each `appKey` here must
          // match the matching `appKey` in navigation.tsx's defaultNavItems.
          { path: 'inventory/*', element: <InventoryPlugin /> },
          {
            path: 'tasks/*',
            element: (
              <AppDisabledGuard appKey="tasks">
                <TasksPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'snippets/*',
            element: (
              <AppDisabledGuard appKey="snippets">
                <SnippetsPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'atw/*',
            element: (
              <AppDisabledGuard appKey="atw">
                <AtwPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'dipper/*',
            element: (
              <AppDisabledGuard appKey="dipper">
                <DipperPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'alerts/templates/*',
            element: (
              <AppDisabledGuard appKey="alerts">
                <AlertsPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'alerts/troubleshooting/*',
            element: (
              <AppDisabledGuard appKey="alert_troubleshooting">
                <AlertTroubleshootingPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'schema-change/alters/*',
            element: (
              <AppDisabledGuard appKey="alters">
                <AltersPlugin />
              </AppDisabledGuard>
            ),
          },
          // Checksums — schema-driven plugin (handles its own sub-routes)
          {
            path: 'plugins/checksums/*',
            element: (
              <AppDisabledGuard appKey="checksums">
                <ChecksumsPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'schema-change/checksums/*',
            element: (
              <AppDisabledGuard appKey="checksums">
                <ChecksumsPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'plugins/mysql_backups/*',
            element: (
              <AppDisabledGuard appKey="mysql_backups">
                <MysqlBackupsPlugin />
              </AppDisabledGuard>
            ),
          },
          { path: 'schema-change/inventory/*', element: <InventoryPlugin /> },
          // NOTE: MySQL Backups lives at /plugins/mysql_backups (above), matching
          // its PLUGIN_BASE_PATH. The old /backups/mysql placeholder route was
          // removed in SEP-1270 — the sidebar now points at the real plugin.
          {
            path: 'backups/mongodb/*',
            element: (
              <AppDisabledGuard appKey="backup_mongo">
                <BackupMongoPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'backups/postgresql/*',
            element: (
              <AppDisabledGuard appKey="backup_pg">
                <BackupPgPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'plugins/archives/*',
            element: (
              <AppDisabledGuard appKey="archives">
                <ArchivesPlugin />
              </AppDisabledGuard>
            ),
          },
          {
            path: 'reports/*',
            element: (
              <AppDisabledGuard appKey="report">
                <ReportPlugin />
              </AppDisabledGuard>
            ),
          },
          { path: 'settings', element: <SettingsPage /> },
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
