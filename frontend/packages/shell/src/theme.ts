// SEP theme — sourced from @percona/percona-ui.
// SepTheme inherits BaseTheme (Poppins headings, semantic tokens) and layers
// SEP brand (purple/yellow), AppBar override, and technology palette.

// Example of how to customize the theme further with overrides and/or new tokens (this is for debugging purposes, do not delete):
/*
import { typographyClasses } from '@mui/material/Typography';
import { sepThemeOptions as sepThemeOptionsOriginal } from '@percona/percona-ui';
import { PaletteMode, ThemeOptions } from '@mui/material';

import { deepmerge } from "@mui/utils";

const sepThemeOptions = (mode: PaletteMode): ThemeOptions => {

  const newOptions: ThemeOptions = {
    components: {
      MuiDrawer: {
        styleOverrides: {
          root: {
            [`.${typographyClasses.root}`]: {
              fontSize: "0.875rem",
            },
          },
        },
      },
    }
  }

  return deepmerge<ThemeOptions>(sepThemeOptionsOriginal(mode), newOptions);
}
export { sepThemeOptions };
*/

export {
  sepThemeOptions,
  sepPrimaryLight,
  sepPrimaryDark,
  sepTechnologyColors,
  primitives,
} from '@percona/percona-ui';
