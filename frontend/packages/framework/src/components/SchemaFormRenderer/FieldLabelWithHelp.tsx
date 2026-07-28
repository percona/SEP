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
  /** Tooltip body shown on hover/focus; also the accessible description. */
  description: string;
  /** Used in the trigger's accessible name (`Help for ${label}`). */
  label: string;
}

/**
 * Info-icon tooltip for schema form field help. Uses a non-button span so it
 * can sit inside MUI floating labels without nesting interactive controls.
 * Focusable via tabIndex so keyboard users can open the tooltip; describeChild
 * keeps aria-label as the accessible name and attaches the description
 * (native title when closed / aria-describedby when open) instead of
 * overriding it. Callers must omit this component when there is no description
 * to show.
 */
export function FieldHelpIcon({ description, label }: FieldHelpIconProps) {
  return (
    <Tooltip title={description} describeChild>
      <Box
        component="span"
        role="img"
        tabIndex={0}
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
  /** Visible field label text. */
  label: string;
  /** Optional help text; when set, an info-icon tooltip is rendered next to the label. */
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
