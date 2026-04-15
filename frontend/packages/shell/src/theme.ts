import type { PaletteMode, ThemeOptions, TypographyVariantsOptions } from '@mui/material';
import { pmmThemeOptions, primitives } from '@percona/percona-ui';

// TODO: remove this when PR on percona-ui is merged
// SEP brand colors
const sepBrand = {
  purple: {
    900: '#2A1A66',
    800: '#3B2790',
    700: '#4D32C3',
    600: '#5A37E0',
    500: '#653DF4',
    400: '#8464F6',
    300: '#9D83F8',
    200: '#BEB0FA',
    100: '#D9D0FC',
    50: '#F2EFFE',
  },
  yellow: {
    900: '#656A23',
    800: '#8A9020',
    700: '#B3BA1C',
    600: '#DCE518',
    500: '#F6FE54',
    400: '#F8FE76',
    300: '#F9FE8E',
    200: '#FBFEB5',
    100: '#FCFED2',
    50: '#FEFFF0',
  },
  black: '#282727',
  white: '#FFFFFF',
} as const;

// Technology colors for charts/badges
export const sepTechnologyColors = {
  mysql: '#E65A15',
  postgresql: '#005ED6',
  mongodb: '#1FA23A',
  kubernetes: '#2AA6DF',
  redis: '#D6362A',
  valkey: '#A83FEF',
} as const;

// SEP Primary color tokens
export const sepPrimaryLight = {
  main: sepBrand.purple[500],
  dark: sepBrand.purple[700],
  light: sepBrand.purple[400],
  contrastText: sepBrand.white,
  hover: 'rgba(101, 61, 244, 0.04)',
  selected: 'rgba(101, 61, 244, 0.08)',
  focus: 'rgba(101, 61, 244, 0.12)',
  focusVisible: 'rgba(101, 61, 244, 0.3)',
  outlinedBorder: 'rgba(101, 61, 244, 0.5)',
};

export const sepPrimaryDark = {
  main: sepBrand.purple[200],
  dark: sepBrand.purple[300],
  light: sepBrand.purple[100],
  contrastText: sepBrand.black,
  hover: 'rgba(190, 176, 250, 0.08)',
  selected: 'rgba(190, 176, 250, 0.12)',
  focus: 'rgba(190, 176, 250, 0.15)',
  focusVisible: 'rgba(190, 176, 250, 0.3)',
  outlinedBorder: 'rgba(190, 176, 250, 0.5)',
};

// SEP Brand Colors
// export const brand = {
//   purple: '#653df4',
//   yellow: '#f6fe54',
//   black: '#282727',
//   white: '#ffffff',
// } as const;

// END TODO

const poppinsHeading = { fontFamily: '"Poppins", sans-serif' };

/**
 * SEP theme options — extends the PMM theme from @percona/percona-ui
 * with SEP-specific brand colors and Poppins headings.
 */
export const sepThemeOptions = (mode: PaletteMode): ThemeOptions => {
  const pmm = pmmThemeOptions(mode);
  const isLight = mode === 'light';

  // TODO: remove this when PR on percona-ui is merged
  const primary = mode === 'light' ? sepPrimaryLight : sepPrimaryDark;

  // PMM typography is always a plain object (not a function) from pmmThemeOptions
  const pmmTypo = pmm.typography as TypographyVariantsOptions;

  return {
    ...pmm,
    palette: {
      ...pmm.palette,
      mode,
      // TODO: remove this when PR on percona-ui is merged
      primary,
      // primary: {
      //   main: isLight ? brand.purple : '#9b7bfa',
      //   light: isLight ? '#8a6df7' : '#b49dfc',
      //   dark: isLight ? '#4a2bb8' : '#653df4',
      //   contrastText: isLight ? brand.white : brand.black,
      // },
      // TODO: is this needed?
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
    // TODO: remove this when PR on percona-ui is merged
    components: {
      ...pmm.components,
      MuiAppBar: {
        styleOverrides: {
          root: () => ({
            color: isLight ? sepBrand.white : sepBrand.black,
            backgroundColor: primary.main,
          }),
        },
      },
    },
  };
};

// Re-export primitives for direct use (Percona color tokens)
export { primitives };
