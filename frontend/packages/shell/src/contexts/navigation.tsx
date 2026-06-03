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

export interface NavItem {
  title: string;
  icon: SvgIconComponent | ((props: SvgIconProps) => React.JSX.Element);
  to?: string;
  children?: NavItem[];
}

// Navigation matching SEP's plugin-based sidebar.
// Backup sub-items use percona-ui's database-specific icons.
//
// URL convention (see SEP-1270): every `to:` here is sourced from the shared
// `ROUTES` map. router.tsx keeps its own `path` literals and is not wired to
// ROUTES, so when a plugin is migrated to React update BOTH the router route
// and the matching ROUTES entry together — never hardcode a path string here.
// Drift between the two is what made the sidebar point at PlaceholderPage /
// NotFoundPage (the regression this ticket fixed for MySQL & Archive); the
// `sidebar-navigation` e2e spec now guards against it. Paths follow three families:
//   • /plugins/<name>  — schema-driven plugins (checksums, mysql_backups, archives)
//   • /backups/<db>    — domain-grouped backup plugins (mongodb, postgresql)
//   • bare top-level   — cross-cutting tools (inventory, tasks, snippets, atw, dipper)
const defaultNavItems: NavItem[] = [
  { title: 'Dashboard', icon: DashboardIcon, to: ROUTES.dashboard },
  { title: 'Inventory', icon: DnsIcon, to: ROUTES.inventory },
  { title: 'Tasks', icon: AssignmentIcon, to: ROUTES.tasks },
  { title: 'Snippets', icon: CodeIcon, to: ROUTES.snippets },
  { title: 'Collect Diagnostic Data', icon: SupportAgentIcon, to: ROUTES.atw },
  {
    title: 'Alerts',
    icon: NotificationsActiveIcon,
    children: [
      { title: 'Templates', icon: DescriptionIcon, to: ROUTES.alertTemplates },
      { title: 'Troubleshooting', icon: TroubleshootIcon, to: ROUTES.alertTroubleshooting },
    ],
  },
  {
    title: 'Schema Change',
    icon: StorageIcon,
    children: [{ title: 'Alters', icon: TableChartIcon, to: ROUTES.schemaAlters }],
  },
  { title: 'Checksums', icon: CheckCircleIcon, to: ROUTES.checksums },
  {
    title: 'Backups',
    icon: BackupIcon,
    children: [
      { title: 'MySQL', icon: MySqlIcon, to: ROUTES.mysqlBackups },
      { title: 'MongoDB', icon: MongoIcon, to: ROUTES.backupsMongodb },
      { title: 'PostgreSQL', icon: PostgreSqlIcon, to: ROUTES.backupsPostgresql },
    ],
  },
  { title: 'Archive', icon: ArchiveIcon, to: ROUTES.archive },
  { title: 'Dipper Data Collection', icon: ScienceIcon, to: ROUTES.dipper },
  { title: 'Reports', icon: BarChartIcon, to: ROUTES.reports },
];

interface NavigationState {
  items: NavItem[];
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

const NavigationContext = createContext<NavigationState | null>(null);

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [items] = useState<NavItem[]>(defaultNavItems);
  const [sidebarOpen, setSidebarOpen] = useState(
    () => window.matchMedia('(min-width: 900px)').matches,
  );

  const toggleSidebar = useCallback(() => {
    setSidebarOpen((prev) => !prev);
  }, []);

  // TODO: fetch from /api/plugins to get enabled plugins
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
