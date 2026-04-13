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
    <ThemeContextProvider
      themeOptions={sepThemeOptions}
      saveColorModeOnLocalStorage
    >
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
