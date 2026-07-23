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
import Tooltip from '@mui/material/Tooltip';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';

export interface FieldHelpIconProps {
  /** Tooltip body; the icon is omitted when this is empty. */
  description: string;
  /** Used in the hover target's accessible name (`Help for ${label}`). */
  label: string;
}

/**
 * Info-icon tooltip for schema form field help. Uses a non-button span so it
 * can sit inside MUI floating labels without nesting interactive controls.
 */
export function FieldHelpIcon({ description, label }: FieldHelpIconProps) {
  return (
    <Tooltip title={description}>
      <Box
        component="span"
        role="img"
        aria-label={`Help for ${label}`}
        sx={{
          display: 'inline-flex',
          alignItems: 'center',
          ml: 0.5,
          verticalAlign: 'middle',
          cursor: 'help',
          color: 'action.active',
        }}
        onClick={(event) => event.preventDefault()}
      >
        <HelpOutlineIcon sx={{ fontSize: 16 }} />
      </Box>
    </Tooltip>
  );
}

export interface FieldLabelWithHelpProps {
  label: string;
  description?: string;
}

/**
 * Field label with an optional info-icon tooltip sourced from `description`.
 * Returns a plain string when there is no description so callers that accept
 * `string | ReactNode` (and undescribed fields) keep a stable, icon-free label.
 */
export function FieldLabelWithHelp({ label, description }: FieldLabelWithHelpProps): ReactNode {
  if (!description) {
    return label;
  }
  return (
    <Box component="span" sx={{ display: 'inline-flex', alignItems: 'center' }}>
      {label}
      <FieldHelpIcon description={description} label={label} />
    </Box>
  );
}
