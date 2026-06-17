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
 * Apps listed here ship custom UI (inventory, tasks, alters, …). Every other
 * known ``app_key`` in ``APP_ROUTE_BY_KEY`` routes through
 * ``SchemaDrivenAppRoute`` instead — no per-app FE package required.
 */

import { createElement, lazy, type ComponentType, type ReactElement } from 'react';
import { SchemaDrivenAppRoute } from './components/SchemaDrivenAppRoute';
import { APP_ROUTE_BY_KEY, getAppRouteMeta } from './appNavConfig';
import { useAuth } from './contexts/auth';

export interface CustomAppRegistryEntry {
  appKey: string;
  routePattern: string;
  Component: ComponentType;
}

export interface SchemaDrivenFallbackRoute {
  appKey: string;
  routePattern: string;
  routeBase?: string;
}

/** Legacy router aliases with no sidebar consumer — kept for bookmark compatibility. */
export interface LegacyRouteAlias {
  path: string;
  appKey: string;
  /** When true, resolve via ``CUSTOM_APP_REGISTRY``; otherwise ``SchemaDrivenAppRoute``. */
  useCustom: boolean;
}

const InventoryPlugin = lazy(() =>
  import('@sep/inventory').then((m) => ({ default: m.InventoryPlugin })),
);
const TasksPlugin = lazy(() =>
  import('@sep/plugin-tasks').then((m) => ({ default: m.TasksPlugin })),
);
const SnippetsPluginLazy = lazy(() =>
  import('@sep/plugins-snippets').then((m) => ({ default: m.SnippetsPlugin })),
);
const AtwPlugin = lazy(() => import('@sep/plugin-atw').then((m) => ({ default: m.AtwPlugin })));
const DipperPlugin = lazy(() =>
  import('@sep/plugin-dipper').then((m) => ({ default: m.DipperPlugin })),
);
const AlertsPlugin = lazy(() =>
  import('@sep/plugin-alerts').then((m) => ({ default: m.AlertsPlugin })),
);
const AlertTroubleshootingPlugin = lazy(() =>
  import('@sep/plugin-alert-troubleshooting').then((m) => ({
    default: m.AlertTroubleshootingPlugin,
  })),
);
const AltersPlugin = lazy(() =>
  import('@sep/plugin-alters').then((m) => ({ default: m.AltersPlugin })),
);
const BackupMongoPlugin = lazy(() =>
  import('@sep/plugin-backup-mongo').then((m) => ({ default: m.BackupMongoPlugin })),
);
const ReportPlugin = lazy(() =>
  import('@sep/plugin-report').then((m) => ({ default: m.ReportPlugin })),
);

function SnippetsPlugin() {
  const { isAdmin } = useAuth();
  return <SnippetsPluginLazy isAdmin={isAdmin} />;
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
  inventory: customEntry('inventory', InventoryPlugin),
  tasks: customEntry('tasks', TasksPlugin),
  snippets: customEntry('snippets', SnippetsPlugin),
  atw: customEntry('atw', AtwPlugin),
  dipper: customEntry('dipper', DipperPlugin),
  alerts: customEntry('alerts', AlertsPlugin),
  alert_troubleshooting: customEntry('alert_troubleshooting', AlertTroubleshootingPlugin),
  alters: customEntry('alters', AltersPlugin),
  backup_mongo: customEntry('backup_mongo', BackupMongoPlugin),
  report: customEntry('report', ReportPlugin),
};

export const LEGACY_ROUTE_ALIASES: LegacyRouteAlias[] = [
  { path: 'schema-change/checksums/*', appKey: 'checksums', useCustom: false },
  { path: 'schema-change/inventory/*', appKey: 'inventory', useCustom: true },
];

/** True when ``appKey`` has a bespoke component in ``CUSTOM_APP_REGISTRY``. */
export function isCustomApp(appKey: string): boolean {
  return appKey in CUSTOM_APP_REGISTRY;
}

/** Schema-driven apps that fall back to ``SchemaDrivenAppRoute`` (not bespoke). */
export function getSchemaDrivenFallbackRoutes(): SchemaDrivenFallbackRoute[] {
  return Object.keys(APP_ROUTE_BY_KEY)
    .filter((appKey) => !isCustomApp(appKey))
    .map((appKey) => {
      const meta = APP_ROUTE_BY_KEY[appKey];
      return {
        appKey,
        routePattern: meta.routePattern,
        routeBase: meta.routeBase,
      };
    });
}

export interface PluginRouteDefinition {
  path: string;
  element: ReactElement;
}

/** Shell plugin routes: bespoke registry entries, schema-driven fallbacks, legacy aliases. */
export function buildPluginRoutes(): PluginRouteDefinition[] {
  const routes: PluginRouteDefinition[] = Object.values(CUSTOM_APP_REGISTRY).map(
    ({ routePattern, Component }) => ({
      path: routePattern,
      element: createElement(Component),
    }),
  );

  for (const { routePattern, appKey } of getSchemaDrivenFallbackRoutes()) {
    routes.push({
      path: routePattern,
      element: createElement(SchemaDrivenAppRoute, { appKey }),
    });
  }

  for (const { path, appKey, useCustom } of LEGACY_ROUTE_ALIASES) {
    if (useCustom) {
      const entry = CUSTOM_APP_REGISTRY[appKey];
      routes.push({
        path,
        element: createElement(entry.Component),
      });
    } else {
      routes.push({
        path,
        element: createElement(SchemaDrivenAppRoute, { appKey }),
      });
    }
  }

  return routes;
}
