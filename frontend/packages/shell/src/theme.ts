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

// SEP theme — sourced from @percona/percona-ui.
// SepTheme inherits BaseTheme (Poppins headings, semantic tokens) and layers
// SEP brand (purple/yellow), AppBar override, and technology palette.

// Example of how to customize the theme further with overrides and/or new tokens (this is for debugging purposes, do not delete):

// import { typographyClasses } from '@mui/material/Typography';
import { sepThemeOptions as sepThemeOptionsOriginal } from '@percona/percona-ui';
import type { PaletteMode, ThemeOptions } from '@mui/material';

import { deepmerge } from '@mui/utils';

const sepThemeOptions = (mode: PaletteMode): ThemeOptions => {
  const newOptions: ThemeOptions = {
    components: {
      MuiButton: {
        variants: [
          { props: { variant: 'contained', color: 'success' }, style: { color: '#fff' } },
          { props: { variant: 'contained', color: 'error' }, style: { color: '#fff' } },
          { props: { variant: 'contained', color: 'warning' }, style: { color: '#fff' } },
          { props: { variant: 'contained', color: 'info' }, style: { color: '#fff' } },
        ],
      },
    },
  };

  return deepmerge<ThemeOptions>(sepThemeOptionsOriginal(mode), newOptions);
};
export { sepThemeOptions };

export {
  // sepThemeOptions,
  sepPrimaryLight,
  sepPrimaryDark,
  sepTechnologyColors,
  primitives,
} from '@percona/percona-ui';
