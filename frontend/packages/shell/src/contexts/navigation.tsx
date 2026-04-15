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
import { MySqlIcon, MongoIcon, PostgreSqlIcon } from '@percona/percona-ui';
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
const defaultNavItems: NavItem[] = [
  { title: 'Dashboard', icon: DashboardIcon, to: '/' },
  { title: 'Inventory', icon: DnsIcon, to: '/inventory' },
  { title: 'Tasks', icon: AssignmentIcon, to: '/tasks' },
  { title: 'Snippets', icon: CodeIcon, to: '/snippets' },
  {
    title: 'Alerts',
    icon: NotificationsActiveIcon,
    children: [
      { title: 'Templates', icon: DescriptionIcon, to: '/alerts/templates' },
      { title: 'Troubleshooting', icon: TroubleshootIcon, to: '/alerts/troubleshooting' },
    ],
  },
  {
    title: 'Schema Change',
    icon: StorageIcon,
    children: [
      { title: 'Alters', icon: TableChartIcon, to: '/schema-change/alters' },
      { title: 'Checksums', icon: CheckCircleIcon, to: '/schema-change/checksums' },
    ],
  },
  {
    title: 'Backups',
    icon: BackupIcon,
    children: [
      { title: 'MySQL', icon: MySqlIcon, to: '/backups/mysql' },
      { title: 'MongoDB', icon: MongoIcon, to: '/backups/mongodb' },
      { title: 'PostgreSQL', icon: PostgreSqlIcon, to: '/backups/postgresql' },
    ],
  },
  { title: 'Archive', icon: ArchiveIcon, to: '/archive' },
  { title: 'Reports', icon: BarChartIcon, to: '/reports' },
];

interface NavigationState {
  items: NavItem[];
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

const NavigationContext = createContext<NavigationState | null>(null);

export function NavigationProvider({ children }: { children: ReactNode }) {
  const [items] = useState<NavItem[]>(defaultNavItems);
  const [sidebarOpen, setSidebarOpen] = useState(true);

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
