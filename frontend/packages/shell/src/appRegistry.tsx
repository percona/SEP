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

/**
 * Frontend ``app_key`` → bespoke React component registry.
 *
 * Apps listed here ship custom UI (inventory, tasks, alters, …). Schema-driven
 * apps carry no entry here — ``SchemaDrivenAppResolver`` (the terminal ``*``
 * route in ``router``) mounts them at render from the ``GET /api/apps`` payload.
 * Legacy route aliases still resolve through ``SchemaDrivenAppRoute``.
 */

import { createElement, lazy, type ComponentType, type ReactElement } from 'react';
import { SchemaDrivenAppRoute } from './components/SchemaDrivenAppRoute';
import { getAppRouteMeta } from './appNavConfig';
import { wrapAppRoute } from './appRouteGuard';
import { useAuth } from './contexts/auth';

export interface CustomAppRegistryEntry {
  appKey: string;
  routePattern: string;
  Component: ComponentType;
}

/** Legacy router aliases with no sidebar consumer — kept for bookmark compatibility. */
export interface LegacyRouteAlias {
  path: string;
  appKey: string;
  /** When true, resolve via ``CUSTOM_APP_REGISTRY``; otherwise ``SchemaDrivenAppRoute``. */
  useCustom: boolean;
}

const InventoryApp = lazy(() =>
  import('@sep/inventory').then((m) => ({ default: m.InventoryApp })),
);
const TasksApp = lazy(() => import('@sep/tasks').then((m) => ({ default: m.TasksApp })));
const SnippetsAppLazy = lazy(() =>
  import('@sep/snippets').then((m) => ({ default: m.SnippetsApp })),
);
const AtwApp = lazy(() => import('@sep/atw').then((m) => ({ default: m.AtwApp })));
const DipperApp = lazy(() => import('@sep/dipper').then((m) => ({ default: m.DipperApp })));
const AlertsApp = lazy(() => import('@sep/alerts').then((m) => ({ default: m.AlertsApp })));
const AlertTroubleshootingApp = lazy(() =>
  import('@sep/alert-troubleshooting').then((m) => ({
    default: m.AlertTroubleshootingApp,
  })),
);
const AltersApp = lazy(() => import('@sep/alters').then((m) => ({ default: m.AltersApp })));
const BackupMongoApp = lazy(() =>
  import('@sep/backup-mongo').then((m) => ({ default: m.BackupMongoApp })),
);
const ReportApp = lazy(() => import('@sep/report').then((m) => ({ default: m.ReportApp })));

function SnippetsApp() {
  const { isAdmin } = useAuth();
  return <SnippetsAppLazy isAdmin={isAdmin} />;
}

function customEntry(appKey: string, Component: ComponentType): CustomAppRegistryEntry {
  const meta = getAppRouteMeta(appKey);
  if (!meta) {
    throw new Error(`Missing route metadata for custom app "${appKey}"`);
  }
  return {
    appKey,
    routePattern: meta.routePattern,
    Component,
  };
}

/** Bespoke apps: one registry entry per ``app_key``. */
export const CUSTOM_APP_REGISTRY: Record<string, CustomAppRegistryEntry> = {
  inventory: customEntry('inventory', InventoryApp),
  tasks: customEntry('tasks', TasksApp),
  snippets: customEntry('snippets', SnippetsApp),
  atw: customEntry('atw', AtwApp),
  dipper: customEntry('dipper', DipperApp),
  alerts: customEntry('alerts', AlertsApp),
  alert_troubleshooting: customEntry('alert_troubleshooting', AlertTroubleshootingApp),
  alters: customEntry('alters', AltersApp),
  backup_mongo: customEntry('backup_mongo', BackupMongoApp),
  report: customEntry('report', ReportApp),
};

export const LEGACY_ROUTE_ALIASES: LegacyRouteAlias[] = [
  { path: 'schema-change/checksums/*', appKey: 'checksums', useCustom: false },
  { path: 'schema-change/inventory/*', appKey: 'inventory', useCustom: true },
];

/** True when ``appKey`` has a bespoke component in ``CUSTOM_APP_REGISTRY``. */
export function isCustomApp(appKey: string): boolean {
  return appKey in CUSTOM_APP_REGISTRY;
}

export interface AppRouteDefinition {
  path: string;
  element: ReactElement;
}

/** Shell app routes: bespoke registry entries + legacy aliases. */
export function buildAppRoutes(): AppRouteDefinition[] {
  const routes: AppRouteDefinition[] = Object.values(CUSTOM_APP_REGISTRY).map(
    ({ appKey, routePattern, Component }) => ({
      path: routePattern,
      element: wrapAppRoute(appKey, createElement(Component)),
    }),
  );

  for (const { path, appKey, useCustom } of LEGACY_ROUTE_ALIASES) {
    if (useCustom) {
      const entry = CUSTOM_APP_REGISTRY[appKey];
      routes.push({
        path,
        element: wrapAppRoute(appKey, createElement(entry.Component)),
      });
    } else {
      routes.push({
        path,
        element: wrapAppRoute(appKey, createElement(SchemaDrivenAppRoute, { appKey })),
      });
    }
  }

  return routes;
}
