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

import type { ReactNode } from 'react';
import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import { useNavigate } from 'react-router-dom';

interface CenteredSplashProps {
  /** Optional decorative element rendered above the title (icon, numeral, …). */
  icon?: ReactNode;
  /** Primary heading line. */
  title: ReactNode;
  /** Secondary explanatory copy. */
  body: ReactNode;
}

/**
 * Centered full-height splash with a "Back to Dashboard" action.
 *
 * Shared layout for the shell's terminal pages (`NotFoundPage`,
 * `AppDisabledPage`) so their styling and navigation can't drift apart over
 * time. Each caller supplies only the icon and copy.
 */
export default function CenteredSplash({ icon, title, body }: CenteredSplashProps) {
  const navigate = useNavigate();

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        py: 10,
        textAlign: 'center',
      }}
    >
      {icon}
      <Typography variant="h6" gutterBottom>
        {title}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {body}
      </Typography>
      <Button variant="contained" onClick={() => navigate('/')}>
        Back to Dashboard
      </Button>
    </Box>
  );
}
