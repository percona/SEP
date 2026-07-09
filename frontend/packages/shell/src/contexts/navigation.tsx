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
import type { SvgIconComponent } from '@mui/icons-material';
import type { SvgIconProps } from '@mui/material';
import { buildNavigationItems } from '../appNavConfig';

// Sidebar tree shape, icons, and React paths live in appNavConfig; labels and
// visibility come from GET /api/apps/ via buildNavigationItems().

export interface NavItem {
  title: string;
  icon: SvgIconComponent | ((props: SvgIconProps) => React.JSX.Element);
  to?: string;
  children?: NavItem[];
  /**
   * Backend app key (the last dotted segment of the app's
   * ``MODULE_NAME``) used to hide this item when the app is disabled. Items
   * without an `appKey` — parent groups, the Dashboard root, and the always-on
   * Inventory app — render unconditionally.
   */
  appKey?: string;
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

  // `data` is undefined only on a cold first load/error; after any success
  // React Query keeps the last-good data across transient refetch errors, so the
  // derived nav stays rendered. The cold case falls back to static-only
  // (Dashboard + Inventory) — the full tree can't be rebuilt without the API data.
  const { data: apps } = useEnabledApps();
  const items = useMemo<NavItem[]>(() => buildNavigationItems(apps), [apps]);

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
