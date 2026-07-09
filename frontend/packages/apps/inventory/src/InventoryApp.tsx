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

import { useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAppSchema, type AppSchema } from '@sep/api';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Tab from '@mui/material/Tab';
import Tabs from '@mui/material/Tabs';
import Typography from '@mui/material/Typography';
import { InventoryBreadcrumbs } from './InventoryAppNavigation';
import { inventoryMountPrefix } from './inventoryNestedPaths';
import { InventoryRoutes } from './InventoryRoutes';

export interface InventoryAppProps {
  /** Optional mock schema for Storybook / offline tests. */
  mockSchema?: AppSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}

/**
 * Inventory app — browse nodes, services, schemas, and tables with the same drill-down
 * as the legacy UI (node → services → schemas → tables). Row delete is available on list
 * tables; detail chrome stays browse-only (no edit / header delete).
 */
export function InventoryApp({ mockSchema, mockEntityItems }: InventoryAppProps) {
  const { data: schema, isLoading, error } = useAppSchema('inventory', mockSchema);

  if (isLoading && !schema) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error && !schema) {
    return (
      <Box sx={{ py: 4 }}>
        <Typography color="error">Failed to load app schema: {error.message}</Typography>
      </Box>
    );
  }

  if (!schema) {
    return null;
  }
  const topologyEnabled = schema.capabilities?.topology === true;

  return (
    <>
      <InventoryViewTabs topologyEnabled={topologyEnabled} />
      <InventoryBreadcrumbs schema={schema} />
      <InventoryRoutes
        schema={schema}
        mockEntityItems={mockEntityItems}
        topologyEnabled={topologyEnabled}
      />
    </>
  );
}

function InventoryViewTabs({ topologyEnabled }: { topologyEnabled: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const prefix = useMemo(() => inventoryMountPrefix(location.pathname), [location.pathname]);
  const value = useMemo(() => {
    if (!prefix) {
      return 'browse';
    }
    return topologyEnabled && location.pathname.startsWith(`${prefix}/topology`)
      ? 'topology'
      : 'browse';
  }, [location.pathname, prefix, topologyEnabled]);

  if (!prefix) {
    return null;
  }

  return (
    <Tabs
      value={value}
      onChange={(_, next) => {
        navigate(next === 'topology' ? `${prefix}/topology` : `${prefix}/nodes`);
      }}
      sx={{ mb: 1 }}
    >
      <Tab value="browse" label="Browse" />
      {topologyEnabled ? <Tab value="topology" label="Topology" /> : null}
    </Tabs>
  );
}
