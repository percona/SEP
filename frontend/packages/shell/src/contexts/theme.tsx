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

import { useContext, type ReactNode } from 'react';
import { ThemeContextProvider, ColorModeContext } from '@percona/percona-ui';
import { sepThemeOptions } from '../theme';

/**
 * SEP theme provider — wraps percona-ui's ThemeContextProvider
 * with SEP-specific theme options derived from PMM theme + brand colors.
 *
 * Uses percona-ui's ColorModeContext for light/dark toggling,
 * with automatic localStorage persistence.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <ThemeContextProvider themeOptions={sepThemeOptions} saveColorModeOnLocalStorage>
      {children}
    </ThemeContextProvider>
  );
}

/**
 * Hook to access the current color mode and toggle function.
 * Delegates to percona-ui's ColorModeContext.
 */
export function useThemeMode() {
  const ctx = useContext(ColorModeContext);
  return {
    mode: ctx.colorMode,
    isDark: ctx.colorMode === 'dark',
    toggle: ctx.toggleColorMode,
  };
}

// Re-export for direct access if needed
export { ColorModeContext };
