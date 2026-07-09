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

import type { Meta, StoryObj } from '@storybook/react-vite';
import Chip from '@mui/material/Chip';
import LinearProgress from '@mui/material/LinearProgress';
import Box from '@mui/material/Box';
import type { ListView } from '@sep/api';
import { SchemaListView, type RenderListColumnOverride } from './SchemaListView';

const listView: ListView = {
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'progress', label: 'Progress' },
    { key: 'status', label: 'Status', format: 'status' },
  ],
};

const data = [
  { id: 1, name: 'nightly-checksum', progress: 100, status: 'completed' },
  { id: 2, name: 'weekly-rebuild', progress: 42, status: 'running' },
  { id: 3, name: 'adhoc-verify', progress: 0, status: 'failed' },
];

const meta: Meta<typeof SchemaListView> = {
  title: 'Framework/SchemaListView',
  component: SchemaListView,
  parameters: { layout: 'padded' },
};
export default meta;

type Story = StoryObj<typeof SchemaListView>;

export const Default: Story = {
  args: { listView, data },
};

/**
 * `renderListColumn` override (SEP-1355). Customizes the `progress` cell with a
 * progress bar and the `status` cell with a coloured chip; the `name` column
 * returns `undefined` so it falls back to the framework's `formatCellValue`.
 */
const renderListColumn: RenderListColumnOverride = ({ columnKey, value }) => {
  if (columnKey === 'progress') {
    const pct = typeof value === 'number' ? value : 0;
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 120 }}>
        <LinearProgress variant="determinate" value={pct} sx={{ flexGrow: 1 }} />
        <span>{pct}%</span>
      </Box>
    );
  }
  if (columnKey === 'status') {
    const str = String(value);
    return (
      <Chip
        label={str}
        size="small"
        variant="outlined"
        color={str === 'completed' ? 'success' : str === 'failed' ? 'error' : 'info'}
      />
    );
  }
  return undefined;
};

export const WithRenderListColumnOverride: Story = {
  args: { listView, data, renderListColumn },
};
