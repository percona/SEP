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
 * Shell sidebar layout and React route metadata per ``app_key``.
 *
 * ``GET /api/apps/`` supplies per-app state and labels (``display_name``,
 * ``enabled``, ``sidebar``). This module holds what the API does not carry —
 * nav tree shape, icons, React route paths, and router patterns — and
 * ``buildNavigationItems()`` merges both into sidebar ``NavItem``s.
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

type NavLeafSkeleton = {
  kind: 'leaf';
  appKey: string;
  icon: NavIcon;
  /** Optimistic sidebar label before ``GET /api/apps/`` resolves. */
  fallbackTitle: string;
};

type NavGroupSkeleton = {
  kind: 'group';
  title: string;
  icon: NavIcon;
  children: NavLeafSkeleton[];
};

type NavStaticSkeleton = {
  kind: 'static';
  title: string;
  icon: NavIcon;
  to: string;
};

type NavSkeletonNode = NavStaticSkeleton | NavGroupSkeleton | NavLeafSkeleton;

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
};

/** Return routing metadata for a registered ``app_key``, if any. */
export function getAppRouteMeta(appKey: string): AppRouteMeta | undefined {
  return APP_ROUTE_BY_KEY[appKey];
}

const NAV_SKELETON: NavSkeletonNode[] = [
  { kind: 'static', title: 'Dashboard', icon: DashboardIcon, to: ROUTES.dashboard },
  { kind: 'static', title: 'Inventory', icon: DnsIcon, to: ROUTES.inventory },
  {
    kind: 'leaf',
    appKey: 'tasks',
    icon: AssignmentIcon,
    fallbackTitle: 'Tasks',
  },
  {
    kind: 'leaf',
    appKey: 'snippets',
    icon: CodeIcon,
    fallbackTitle: 'Snippets',
  },
  {
    kind: 'leaf',
    appKey: 'atw',
    icon: SupportAgentIcon,
    fallbackTitle: 'Collect Diagnostic Data',
  },
  {
    kind: 'group',
    title: 'Alerts',
    icon: NotificationsActiveIcon,
    children: [
      {
        kind: 'leaf',
        appKey: 'alerts',
        icon: DescriptionIcon,
        fallbackTitle: 'Templates',
      },
      {
        kind: 'leaf',
        appKey: 'alert_troubleshooting',
        icon: TroubleshootIcon,
        fallbackTitle: 'Troubleshooting',
      },
    ],
  },
  {
    kind: 'group',
    title: 'Schema Change',
    icon: StorageIcon,
    children: [
      {
        kind: 'leaf',
        appKey: 'alters',
        icon: TableChartIcon,
        fallbackTitle: 'Alters',
      },
    ],
  },
  {
    kind: 'leaf',
    appKey: 'checksums',
    icon: CheckCircleIcon,
    fallbackTitle: 'Checksums',
  },
  {
    kind: 'group',
    title: 'Backups',
    icon: BackupIcon,
    children: [
      {
        kind: 'leaf',
        appKey: 'mysql_backups',
        icon: MySqlIcon,
        fallbackTitle: 'MySQL',
      },
      {
        kind: 'leaf',
        appKey: 'backup_mongo',
        icon: MongoIcon,
        fallbackTitle: 'MongoDB',
      },
      {
        kind: 'leaf',
        appKey: 'backup_pg',
        icon: PostgreSqlIcon,
        fallbackTitle: 'PostgreSQL',
      },
    ],
  },
  {
    kind: 'leaf',
    appKey: 'archives',
    icon: ArchiveIcon,
    fallbackTitle: 'Archive',
  },
  {
    kind: 'leaf',
    appKey: 'dipper',
    icon: ScienceIcon,
    fallbackTitle: 'Dipper Data Collection',
  },
  {
    kind: 'leaf',
    appKey: 'report',
    icon: BarChartIcon,
    fallbackTitle: 'Reports',
  },
];

function leafToNavItem(
  leaf: NavLeafSkeleton,
  appsByKey: Map<string, EnabledApp> | undefined,
): NavItem | null {
  const route = getAppRouteMeta(leaf.appKey);
  const to = route?.reactRoute;
  if (!to) {
    return null;
  }

  if (appsByKey) {
    const app = appsByKey.get(leaf.appKey);
    if (!app?.enabled || !app.sidebar) {
      return null;
    }
    return {
      title: app.display_name,
      icon: leaf.icon,
      to,
      appKey: leaf.appKey,
    };
  }

  return {
    title: leaf.fallbackTitle,
    icon: leaf.icon,
    to,
    appKey: leaf.appKey,
  };
}

function skeletonToNavItems(
  nodes: NavSkeletonNode[],
  appsByKey: Map<string, EnabledApp> | undefined,
): NavItem[] {
  return nodes.reduce<NavItem[]>((acc, node) => {
    if (node.kind === 'static') {
      acc.push({ title: node.title, icon: node.icon, to: node.to });
      return acc;
    }

    if (node.kind === 'leaf') {
      const item = leafToNavItem(node, appsByKey);
      if (item) {
        acc.push(item);
      }
      return acc;
    }

    const children = skeletonToNavItems(node.children, appsByKey);
    if (children.length > 0) {
      acc.push({ title: node.title, icon: node.icon, children });
    }
    return acc;
  }, []);
}

/**
 * Build sidebar navigation from the static layout skeleton and optional API apps.
 *
 * When ``apps`` is undefined (query loading or failed), every skeleton entry
 * renders optimistically with ``fallbackTitle`` labels. Once loaded, entries
 * are hidden when ``enabled`` or ``sidebar`` is false and leaf labels come
 * from ``display_name``.
 */
export function buildNavigationItems(apps: EnabledApp[] | undefined): NavItem[] {
  const appsByKey = apps ? new Map(apps.map((app) => [app.app_key, app])) : undefined;
  return skeletonToNavItems(NAV_SKELETON, appsByKey);
}
