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
 * Shell sidebar chrome and React route metadata per ``app_key``.
 *
 * ``GET /api/apps/`` supplies per-app state, labels, and placement
 * (``display_name``, ``enabled``, ``sidebar``, ``group``, ``nav_order``).
 * ``buildNavigationItems()`` derives the sidebar tree from that data (each
 * leaf's icon, and its ``to`` for schema-driven apps); this module holds only
 * what the API does not carry — group labels/icons, the icon-key → component
 * map, the static (non-app) entries, and the custom-app React route patterns
 * (which also supply custom apps' sidebar ``to``).
 */

import type { EnabledApp } from '@sep/api';
import DashboardIcon from '@mui/icons-material/Dashboard';
import DnsIcon from '@mui/icons-material/Dns';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import BackupIcon from '@mui/icons-material/Backup';
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart';
import ExtensionIcon from '@mui/icons-material/Extension';
import { ROUTES } from '@sep/shared';
import { ICON_BY_KEY } from './generated/appNavIcons';
import type { NavIcon, NavItem } from './contexts/navigation';

/** React routing metadata keyed by backend ``app_key``. */
export interface AppRouteMeta {
  appKey: string;
  /** Sidebar link target (canonical React path — not raw API ``uri_path``). */
  reactRoute: string;
  /** ``react-router`` path literal relative to ``MainLayout`` (e.g. ``apps/archives/*``). */
  routePattern: string;
  /** ``SchemaDrivenApp`` list/detail prefix when not ``/apps/{appKey}``. */
  routeBase?: string;
}

export function toRoutePattern(reactRoute: string): string {
  const trimmed = reactRoute.replace(/^\//, '');
  return trimmed.length > 0 ? `${trimmed}/*` : '*';
}

function defineAppRoute(appKey: string, reactRoute: string, routeBase?: string): AppRouteMeta {
  return {
    appKey,
    reactRoute,
    routePattern: toRoutePattern(reactRoute),
    routeBase,
  };
}

/**
 * Canonical React paths and router patterns per custom-UI ``app_key``.
 *
 * Only bespoke React apps live here — ``customEntry()`` reads each entry's
 * ``routePattern`` at router-build time. Schema-driven apps no longer need an
 * entry: their route is carried on the ``GET /api/apps`` payload's
 * ``react_route`` and mounted at render by ``SchemaDrivenAppResolver``.
 */
export const APP_ROUTE_BY_KEY: Record<string, AppRouteMeta> = {
  inventory: defineAppRoute('inventory', ROUTES.inventory, ROUTES.inventory),
  tasks: defineAppRoute('tasks', ROUTES.tasks, ROUTES.tasks),
  snippets: defineAppRoute('snippets', ROUTES.snippets, ROUTES.snippets),
  atw: defineAppRoute('atw', ROUTES.atw, ROUTES.atw),
  alerts: defineAppRoute('alerts', ROUTES.alertTemplates, ROUTES.alertTemplates),
  alert_troubleshooting: defineAppRoute(
    'alert_troubleshooting',
    ROUTES.alertTroubleshooting,
    ROUTES.alertTroubleshooting,
  ),
  alters: defineAppRoute('alters', ROUTES.schemaAlters, ROUTES.schemaAlters),
  backup_mongo: defineAppRoute('backup_mongo', ROUTES.backupsMongodb, ROUTES.backupsMongodb),
  dipper: defineAppRoute('dipper', ROUTES.dipper, ROUTES.dipper),
  topology: defineAppRoute('topology', ROUTES.topology, ROUTES.topology),
  report: defineAppRoute('report', ROUTES.reports, ROUTES.reports),
};

/** Return routing metadata for a registered ``app_key``, if any. */
export function getAppRouteMeta(appKey: string): AppRouteMeta | undefined {
  return APP_ROUTE_BY_KEY[appKey];
}

/** Label and icon per backend group key (``app.group``). */
const NAV_GROUPS: Record<string, { label: string; icon: NavIcon }> = {
  backups: { label: 'Backups', icon: BackupIcon },
  alerts: { label: 'Alerts', icon: NotificationsActiveIcon },
  diagnostics: { label: 'Diagnostics', icon: MonitorHeartIcon },
};

const DEFAULT_APP_ICON: NavIcon = ExtensionIcon;

/** Always-on non-app destinations, prepended ahead of the derived app tree. */
const STATIC_NAV_ENTRIES: NavItem[] = [
  { title: 'Dashboard', icon: DashboardIcon, to: ROUTES.dashboard },
  { title: 'Inventory', icon: DnsIcon, to: ROUTES.inventory },
];

/** App keys handled by static chrome above; excluded from the derived tree. */
const STATIC_APP_KEYS = new Set(['inventory']);

type TopLevelEntry = { order: number | null; key: string; item: NavItem };

/** Compare by ``nav_order`` (``null`` last), then by key for a stable tie-break. */
function byOrderThenKey(
  a: { order: number | null; key: string },
  b: { order: number | null; key: string },
): number {
  const aOrder = a.order ?? Number.POSITIVE_INFINITY;
  const bOrder = b.order ?? Number.POSITIVE_INFINITY;
  if (aOrder !== bOrder) {
    return aOrder - bOrder;
  }
  return a.key.localeCompare(b.key);
}

/**
 * Build a leaf nav item for one app.
 *
 * ``to`` prefers the frontend route registry when the app has an entry there —
 * i.e. a custom-UI app, whose bespoke component is mounted at that registered
 * path — so its link always matches what actually mounts (a backend
 * ``react_route`` override can never strand a custom app on the 404 resolver).
 * Schema-driven apps have no registry entry, so their link falls through to the
 * backend ``react_route`` that ``SchemaDrivenAppResolver`` mounts them at.
 */
function leafNavItem(app: EnabledApp): NavItem {
  return {
    title: app.display_name,
    icon: (app.nav_icon ? ICON_BY_KEY[app.nav_icon] : undefined) ?? DEFAULT_APP_ICON,
    to: getAppRouteMeta(app.app_key)?.reactRoute ?? app.react_route,
    appKey: app.app_key,
  };
}

/**
 * Derive sidebar navigation items from the API's per-app placement data.
 *
 * When ``apps`` is undefined (a cold first load or a cold first-load error,
 * with no React Query cache to fall back on) only the static Dashboard +
 * Inventory entries render. After a successful load, React Query retains the
 * last-good data across transient errors, so the full derived tree stays.
 *
 * Visible apps (``enabled``, ``sidebar``, excluding the statically-handled keys
 * and nested sub-app keys) are partitioned into groups and ungrouped leaves;
 * each group sorts by its lowest child ``nav_order`` and is hidden when it has
 * no visible children.
 */
export function buildNavigationItems(apps: EnabledApp[] | undefined): NavItem[] {
  if (!apps) {
    return [...STATIC_NAV_ENTRIES];
  }

  const visible = apps.filter(
    (app) =>
      app.enabled && app.sidebar && !STATIC_APP_KEYS.has(app.app_key) && !app.app_key.includes('/'),
  );

  const grouped = new Map<string, EnabledApp[]>();
  const topLevel: TopLevelEntry[] = [];

  for (const app of visible) {
    const groupKey = app.group && NAV_GROUPS[app.group] ? app.group : undefined;
    if (groupKey) {
      const members = grouped.get(groupKey) ?? [];
      members.push(app);
      grouped.set(groupKey, members);
    } else {
      topLevel.push({ order: app.nav_order, key: app.app_key, item: leafNavItem(app) });
    }
  }

  for (const [groupKey, members] of grouped) {
    const sortedMembers = [...members].sort((a, b) =>
      byOrderThenKey(
        { order: a.nav_order, key: a.app_key },
        { order: b.nav_order, key: b.app_key },
      ),
    );
    const minOrder = sortedMembers[0].nav_order;
    const { label, icon } = NAV_GROUPS[groupKey];
    topLevel.push({
      order: minOrder,
      key: groupKey,
      item: { title: label, icon, children: sortedMembers.map(leafNavItem) },
    });
  }

  topLevel.sort(byOrderThenKey);

  return [...STATIC_NAV_ENTRIES, ...topLevel.map((entry) => entry.item)];
}
