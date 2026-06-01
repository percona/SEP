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

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useEnabledApps } from '@sep/api';
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
import type { SvgIconComponent } from '@mui/icons-material';
import type { SvgIconProps } from '@mui/material';

export interface NavItem {
  title: string;
  icon: SvgIconComponent | ((props: SvgIconProps) => React.JSX.Element);
  to?: string;
  children?: NavItem[];
  /**
   * Backend plugin key (the last dotted segment of the plugin's
   * ``MODULE_NAME``) used to hide this item when the app is disabled. Items
   * without an `appKey` — parent groups, the Dashboard root, and the always-on
   * Inventory app — render unconditionally.
   */
  appKey?: string;
}

// Navigation matching SEP's plugin-based sidebar. Each `appKey` is the backend
// plugin module key consumed by `GET /api/apps/` to drive enable/disable.
// Backup sub-items use percona-ui's database-specific icons.
const defaultNavItems: NavItem[] = [
  { title: 'Dashboard', icon: DashboardIcon, to: '/' },
  { title: 'Inventory', icon: DnsIcon, to: '/inventory' },
  { title: 'Tasks', icon: AssignmentIcon, to: '/tasks', appKey: 'tasks' },
  { title: 'Snippets', icon: CodeIcon, to: '/snippets', appKey: 'snippets' },
  { title: 'Collect Diagnostic Data', icon: SupportAgentIcon, to: '/atw', appKey: 'atw' },
  {
    title: 'Alerts',
    icon: NotificationsActiveIcon,
    children: [
      { title: 'Templates', icon: DescriptionIcon, to: '/alerts/templates', appKey: 'alerts' },
      {
        title: 'Troubleshooting',
        icon: TroubleshootIcon,
        to: '/alerts/troubleshooting',
        appKey: 'alert_troubleshooting',
      },
    ],
  },
  {
    title: 'Schema Change',
    icon: StorageIcon,
    children: [
      { title: 'Alters', icon: TableChartIcon, to: '/schema-change/alters', appKey: 'alters' },
    ],
  },
  { title: 'Checksums', icon: CheckCircleIcon, to: '/plugins/checksums', appKey: 'checksums' },
  {
    title: 'Backups',
    icon: BackupIcon,
    children: [
      { title: 'MySQL', icon: MySqlIcon, to: '/backups/mysql', appKey: 'mysql_backups' },
      { title: 'MongoDB', icon: MongoIcon, to: '/backups/mongodb', appKey: 'backup_mongo' },
      { title: 'PostgreSQL', icon: PostgreSqlIcon, to: '/backups/postgresql', appKey: 'backup_pg' },
    ],
  },
  { title: 'Archive', icon: ArchiveIcon, to: '/archive', appKey: 'archives' },
  { title: 'Dipper Data Collection', icon: ScienceIcon, to: '/dipper', appKey: 'dipper' },
  { title: 'Reports', icon: BarChartIcon, to: '/reports', appKey: 'report' },
];

/**
 * Filter a navigation tree by the set of enabled app keys.
 *
 * An item is hidden when it carries an `appKey` that is not in `enabledKeys`.
 * Items without an `appKey` (the Dashboard root, the Inventory app, parent
 * groups) always render. A parent group is hidden once all of its children are
 * hidden. The input is not mutated.
 */
export function filterNavByEnabledApps(items: NavItem[], enabledKeys: Set<string>): NavItem[] {
  return items.reduce<NavItem[]>((acc, item) => {
    if (item.children) {
      const children = filterNavByEnabledApps(item.children, enabledKeys);
      if (children.length > 0) {
        acc.push({ ...item, children });
      }
    } else if (item.appKey === undefined || enabledKeys.has(item.appKey)) {
      acc.push(item);
    }
    return acc;
  }, []);
}

interface NavigationState {
  items: NavItem[];
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

const NavigationContext = createContext<NavigationState | null>(null);

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.matchMedia('(min-width: 900px)').matches,
  );

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => !prev);
  }, []);

  // Filter the static nav by runtime app state. Until the query resolves (or if
  // it fails), `data` is undefined and the full nav renders optimistically — a
  // brief flash of the unfiltered nav is acceptable, and a fetch error must not
  // strand the user with an empty sidebar.
  const { data: apps } = useEnabledApps();
  const items = useMemo<NavItem[]>(() => {
    if (!apps) {
      return defaultNavItems;
    }
    const enabledKeys = new Set(apps.filter((app) => app.enabled).map((app) => app.app_key));
    return filterNavByEnabledApps(defaultNavItems, enabledKeys);
  }, [apps]);

  const value = useMemo<NavigationState>(
    () => ({ items, sidebarOpen, toggleSidebar }),
    [items, sidebarOpen, toggleSidebar],
  );

  return <NavigationContext value={value}>{children}</NavigationContext>;
}

export function useNavigation(): NavigationState {
  const ctx = useContext(NavigationContext);
  if (!ctx) {
    throw new Error('useNavigation must be used within NavigationProvider');
  }
  return ctx;
}
