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
 * ``buildNavigationItems()`` derives the sidebar tree from that data; this
 * module holds only what the API does not carry — group labels/icons, per-app
 * icons, the static (non-app) entries, and React route paths/patterns.
 */

import type { EnabledApp } from '@sep/api';
import DashboardIcon from '@mui/icons-material/Dashboard';
import DnsIcon from '@mui/icons-material/Dns';
import AssignmentIcon from '@mui/icons-material/Assignment';
import CodeIcon from '@mui/icons-material/Code';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import DescriptionIcon from '@mui/icons-material/Description';
import TroubleshootIcon from '@mui/icons-material/Troubleshoot';
import StorageIcon from '@mui/icons-material/Storage';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import TableChartIcon from '@mui/icons-material/TableChart';
import BackupIcon from '@mui/icons-material/Backup';
import ArchiveIcon from '@mui/icons-material/Archive';
import BarChartIcon from '@mui/icons-material/BarChart';
import SupportAgentIcon from '@mui/icons-material/SupportAgent';
import ScienceIcon from '@mui/icons-material/Science';
import ExtensionIcon from '@mui/icons-material/Extension';
import GroupIcon from '@mui/icons-material/Group';
import SystemUpdateAltIcon from '@mui/icons-material/SystemUpdateAlt';
import { MySqlIcon, MongoIcon, PostgreSqlIcon } from '@percona/percona-ui';
import { ROUTES } from '@sep/shared';
import type { SvgIconComponent } from '@mui/icons-material';
import type { SvgIconProps } from '@mui/material';
import type { NavItem } from './contexts/navigation';

export type NavIcon = SvgIconComponent | ((props: SvgIconProps) => React.JSX.Element);

/** React routing metadata keyed by backend ``app_key``. */
export interface AppRouteMeta {
  appKey: string;
  /** Sidebar link target (canonical React path — not raw API ``uri_path``). */
  reactRoute: string;
  /** ``react-router`` path literal relative to ``MainLayout`` (e.g. ``plugins/archives/*``). */
  routePattern: string;
  /** ``SchemaDrivenPlugin`` list/detail prefix when not ``/plugins/{appKey}``. */
  routeBase?: string;
}

function toRoutePattern(reactRoute: string): string {
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

/** Canonical React paths and router patterns per ``app_key``. */
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
  checksums: defineAppRoute('checksums', ROUTES.checksums),
  mysql_backups: defineAppRoute('mysql_backups', ROUTES.mysqlBackups),
  backup_mongo: defineAppRoute('backup_mongo', ROUTES.backupsMongodb, ROUTES.backupsMongodb),
  backup_pg: defineAppRoute('backup_pg', ROUTES.backupsPostgresql, ROUTES.backupsPostgresql),
  archives: defineAppRoute('archives', ROUTES.archive),
  dipper: defineAppRoute('dipper', ROUTES.dipper, ROUTES.dipper),
  report: defineAppRoute('report', ROUTES.reports, ROUTES.reports),
  mum: defineAppRoute('mum', '/mum'),
  mongo_upgrade: defineAppRoute('mongo_upgrade', ROUTES.mongoUpgrade),
};

/** Return routing metadata for a registered ``app_key``, if any. */
export function getAppRouteMeta(appKey: string): AppRouteMeta | undefined {
  return APP_ROUTE_BY_KEY[appKey];
}

/** Label and icon per backend group key (``app.group``). */
const NAV_GROUPS: Record<string, { label: string; icon: NavIcon }> = {
  backups: { label: 'Backups', icon: BackupIcon },
  alerts: { label: 'Alerts', icon: NotificationsActiveIcon },
  schema_change: { label: 'Schema Change', icon: StorageIcon },
  snippets: { label: 'Snippets', icon: CodeIcon },
};

const DEFAULT_APP_ICON: NavIcon = ExtensionIcon;

/** Sidebar icon per ``app_key``; falls back to ``DEFAULT_APP_ICON``. */
const APP_NAV_ICONS: Record<string, NavIcon> = {
  tasks: AssignmentIcon,
  snippets: CodeIcon,
  atw: SupportAgentIcon,
  alerts: DescriptionIcon,
  alert_troubleshooting: TroubleshootIcon,
  alters: TableChartIcon,
  checksums: CheckCircleIcon,
  mysql_backups: MySqlIcon,
  backup_mongo: MongoIcon,
  backup_pg: PostgreSqlIcon,
  archives: ArchiveIcon,
  dipper: ScienceIcon,
  report: BarChartIcon,
  mum: GroupIcon,
  mongo_upgrade: SystemUpdateAltIcon,
};

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

function leafNavItem(app: EnabledApp): NavItem {
  return {
    title: app.display_name,
    icon: APP_NAV_ICONS[app.app_key] ?? DEFAULT_APP_ICON,
    to: getAppRouteMeta(app.app_key)?.reactRoute,
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
 * Visible apps (``enabled``, ``sidebar``, with a known route, excluding the
 * statically-handled keys) are partitioned into groups and ungrouped leaves;
 * each group sorts by its lowest child ``nav_order`` and is hidden when it has
 * no visible children.
 */
export function buildNavigationItems(apps: EnabledApp[] | undefined): NavItem[] {
  if (!apps) {
    return [...STATIC_NAV_ENTRIES];
  }

  const visible = apps.filter(
    (app) =>
      app.enabled &&
      app.sidebar &&
      !STATIC_APP_KEYS.has(app.app_key) &&
      getAppRouteMeta(app.app_key) !== undefined,
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
