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

import { useEffect, useState } from 'react';
import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import SettingRow from './SettingRow';
import { type GroupNode, countLeaves, countOverriddenLeaves, groupNodeId } from './settingField';

export interface NestedSettingGroupProps {
  node: GroupNode;
  /**
   * Expand on mount. Driven by an active search so a leaf that matched a
   * key-substring search is visible even though groups are collapsed by default.
   */
  searchActive?: boolean;
}

/**
 * An expandable parent row for a nested (submodel) setting. Collapsed by
 * default, it summarises the parent segment, how many nested leaves it holds,
 * and how many currently carry an override. Expanding renders one editable row
 * per nested leaf (reusing {@link SettingRow}, which addresses save/reset by the
 * leaf's own `PARENT__CHILD` key) and recurses one level for two-level nesting.
 */
export default function NestedSettingGroup({
  node,
  searchActive = false,
}: NestedSettingGroupProps) {
  const leafCount = countLeaves(node);
  const overriddenCount = countOverriddenLeaves(node);

  // Expansion is controlled so toggling a search auto-expands the group WITHOUT
  // remounting its subtree (a remount would discard any in-flight leaf edit or
  // inline validation). An active search forces it open; the user can still
  // collapse/expand freely while browsing.
  const [expanded, setExpanded] = useState(searchActive);
  useEffect(() => {
    if (searchActive) {
      setExpanded(true);
    }
  }, [searchActive]);

  return (
    <Accordion
      expanded={expanded}
      onChange={(_event, isExpanded) => setExpanded(isExpanded)}
      disableGutters
      data-testid={`nested-setting-group-${groupNodeId(node)}`}
      sx={{ boxShadow: 'none', '&:before': { display: 'none' } }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon />}
        aria-label={`${node.segment} nested settings`}
        sx={{ borderBottom: 1, borderColor: 'divider', px: 1 }}
      >
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Typography variant="body2" sx={{ fontFamily: 'monospace', fontWeight: 600 }}>
            {node.segment}
          </Typography>
          <Chip size="small" variant="outlined" label="nested" />
          <Typography variant="caption" color="text.secondary">
            {leafCount} {leafCount === 1 ? 'field' : 'fields'}
            {overriddenCount > 0 ? `, ${overriddenCount} overridden` : ''}
          </Typography>
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ p: 0, pl: 2 }}>
        {node.children.map((child) =>
          child.kind === 'group' ? (
            <NestedSettingGroup
              key={`group:${groupNodeId(child)}`}
              node={child}
              searchActive={searchActive}
            />
          ) : (
            <Box key={`leaf:${child.setting.setting_class}.${child.setting.key}`}>
              <SettingRow setting={child.setting} />
            </Box>
          ),
        )}
      </AccordionDetails>
    </Accordion>
  );
}
