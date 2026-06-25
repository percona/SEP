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

import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import Typography from '@mui/material/Typography';
import type { SettingResponse } from '@sep/api';

import SettingRow from './SettingRow';
import NestedSettingGroup from './NestedSettingGroup';
import { buildSettingTree, groupNodeId } from './settingField';

export interface SettingsGroupProps {
  settingClass: string;
  settings: SettingResponse[];
  defaultExpanded?: boolean;
  /** Whether a key search is active (auto-expands nested groups). */
  searchActive?: boolean;
}

/** One expandable section per `setting_class`, listing its setting rows. */
export default function SettingsGroup({
  settingClass,
  settings,
  defaultExpanded = true,
  searchActive = false,
}: SettingsGroupProps) {
  const tree = buildSettingTree(settings);
  return (
    <Accordion defaultExpanded={defaultExpanded} data-testid={`settings-group-${settingClass}`}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center">
          <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
            {settingClass}
          </Typography>
          <Chip size="small" label={tree.length} />
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        {tree.map((node) =>
          node.kind === 'group' ? (
            <NestedSettingGroup
              key={`group:${groupNodeId(node)}`}
              node={node}
              searchActive={searchActive}
            />
          ) : (
            <SettingRow
              key={`${node.setting.setting_class}.${node.setting.key}`}
              setting={node.setting}
            />
          ),
        )}
      </AccordionDetails>
    </Accordion>
  );
}
