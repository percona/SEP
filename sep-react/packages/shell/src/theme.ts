import type { PaletteMode, ThemeOptions, TypographyVariantsOptions } from '@mui/material';
import { pmmThemeOptions, primitives } from '@percona/percona-ui';

// SEP Brand Colors
export const brand = {
  purple: '#653df4',
  yellow: '#f6fe54',
  black: '#282727',
  white: '#ffffff',
} as const;

// Technology colors — used for service-type indicators
export const techColors = {
  mysql: '#e65a15',
  postgresql: '#005ed6',
  mongodb: '#1fa23a',
  kubernetes: '#2aa6df',
  redis: '#d6362a',
  valkey: '#a83fef',
} as const;

const poppinsHeading = { fontFamily: '"Poppins", sans-serif' };

/**
 * SEP theme options — extends the PMM theme from @percona/percona-ui
 * with SEP-specific brand colors and Poppins headings.
 */
export const sepThemeOptions = (mode: PaletteMode): ThemeOptions => {
  const pmm = pmmThemeOptions(mode);
  const isLight = mode === 'light';

  // PMM typography is always a plain object (not a function) from pmmThemeOptions
  const pmmTypo = pmm.typography as TypographyVariantsOptions;

  return {
    ...pmm,
    palette: {
      ...pmm.palette,
      mode,
      // primary: {
      //   main: isLight ? brand.purple : '#9b7bfa',
      //   light: isLight ? '#8a6df7' : '#b49dfc',
      //   dark: isLight ? '#4a2bb8' : '#653df4',
      //   contrastText: isLight ? brand.white : brand.black,
      // },
      // secondary: {
      //   main: brand.yellow,
      //   light: '#f8fe86',
      //   dark: '#c4cb43',
      //   contrastText: brand.black,
      // },
    },
    typography: {
      ...pmmTypo,
      h1: { ...pmmTypo.h1, ...poppinsHeading, fontWeight: 600 },
      h2: { ...pmmTypo.h2, ...poppinsHeading, fontWeight: 600 },
      h3: { ...pmmTypo.h3, ...poppinsHeading, fontWeight: 600 },
      h4: { ...pmmTypo.h4, ...poppinsHeading, fontWeight: 500 },
      h5: { ...pmmTypo.h5, ...poppinsHeading, fontWeight: 500 },
      h6: { ...pmmTypo.h6, ...poppinsHeading, fontWeight: 500 },
    },
    components: {
      ...pmm.components,
      MuiAppBar: {
        styleOverrides: {
          root: () => ({
            color: isLight ? brand.white : brand.black,
            backgroundColor: isLight ? brand.purple : '#9b7bfa',
          }),
        },
      },
    }
  };
};

// Re-export primitives for direct use (Percona color tokens)
export { primitives };
