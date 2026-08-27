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

import { useAppSchema, type AppSchema } from '@sep/api';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import { InventoryBreadcrumbs } from './InventoryAppNavigation';
import { InventoryRoutes } from './InventoryRoutes';

export interface InventoryAppProps {
  /** Optional mock schema for Storybook / offline tests. */
  mockSchema?: AppSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}

/**
 * Inventory app — browse nodes, services, schemas, and tables with the same drill-down
 * as the legacy UI (node → services → schemas → tables). Entities are browse-only —
 * no create, no edit, no row or header delete — since PMM authors them; syncing and
 * schedule management stay available.
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

  return (
    <>
      <InventoryBreadcrumbs schema={schema} />
      <InventoryRoutes schema={schema} mockEntityItems={mockEntityItems} />
    </>
  );
}
