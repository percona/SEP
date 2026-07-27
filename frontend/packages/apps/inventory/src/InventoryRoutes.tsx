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

import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import ScheduleIcon from '@mui/icons-material/Schedule';
import DeviceHubIcon from '@mui/icons-material/DeviceHub';
import type { AppSchema } from '@sep/api';
import { AppDetailPage, AppListPage } from '@sep/framework';
import { renderInventoryDetailChildren } from './InventoryAppNavigation';
import { inventoryMountPrefix, pathToNestedInventoryParent } from './inventoryNestedPaths';
import { SyncControl } from './SyncControl';
import { InventoryScheduleSummary } from './InventoryScheduleSummary';
import { InventorySchedulePage } from './InventorySchedulePage';
import { TargetHostsPage } from './TargetHostsPage';

const INVENTORY_DETAIL_SUPPRESS_KEYS = [
  'services',
  'schemas',
  'tables',
  'node',
  'service',
  'database',
];

function InventoryNodesList({
  schema,
  mockEntityItems,
  allowListEntityDelete,
  schedulingEnabled,
}: {
  schema: AppSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  allowListEntityDelete: boolean;
  schedulingEnabled: boolean;
}) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1,
          mb: 1,
        }}
      >
        <InventoryScheduleSummary schedulingEnabled={schedulingEnabled} />
        <Box
          sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1, flexShrink: 0, ml: 'auto' }}
        >
          <Button
            variant="outlined"
            startIcon={<DeviceHubIcon />}
            onClick={() => navigate('../target-hosts', { relative: 'path' })}
            data-testid="inv-target-hosts-link"
          >
            Target hosts
          </Button>
          {schedulingEnabled && (
            <Button
              variant="outlined"
              startIcon={<ScheduleIcon />}
              onClick={() => navigate('../schedule', { relative: 'path' })}
              data-testid="inv-schedule-link"
            >
              Schedules
            </Button>
          )}
          <SyncControl />
        </Box>
      </Box>
      <AppListPage
        schema={schema}
        pluginName="inventory"
        mockEntityItems={mockEntityItems}
        listOnly={false}
        hideCreate
        hideEntityTabs
        hideScheduleButton
        entityNameOverride="nodes"
        rowClickHref={(row) => `${pathname}/${String(row.id)}`}
        allowListEntityDelete={allowListEntityDelete}
      />
    </>
  );
}

function nestedParentPath(pathname: string): string | null {
  const prefix = inventoryMountPrefix(pathname);
  return prefix ? pathToNestedInventoryParent(pathname, prefix) : null;
}

export function InventoryRoutes({
  schema,
  mockEntityItems,
}: {
  schema: AppSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}) {
  const schedulingEnabled = !!schema.capabilities?.scheduling;
  const detailProps = {
    schema,
    pluginName: 'inventory',
    mockEntityItems,
    browseOnly: true,
    suppressDetailKeys: INVENTORY_DETAIL_SUPPRESS_KEYS,
    renderEntityDetailChildren: renderInventoryDetailChildren,
    hideDetailChrome: true,
    allowListEntityDelete: true,
  };

  return (
    <Routes>
      <Route index element={<Navigate to="nodes" replace />} />
      <Route
        path="nodes"
        element={
          <InventoryNodesList
            schema={schema}
            mockEntityItems={mockEntityItems}
            allowListEntityDelete
            schedulingEnabled={schedulingEnabled}
          />
        }
      />
      <Route
        path="schedule"
        element={<InventorySchedulePage schedulingEnabled={schedulingEnabled} />}
      />
      <Route path="target-hosts" element={<TargetHostsPage />} />
      <Route
        path="nodes/:nodeId"
        element={
          <AppDetailPage
            {...detailProps}
            detailEntityName="nodes"
            detailIdParam="nodeId"
            resolveParentPath={nestedParentPath}
          />
        }
      />
      <Route
        path="nodes/:nodeId/services/:serviceId"
        element={
          <AppDetailPage
            {...detailProps}
            detailEntityName="services"
            detailIdParam="serviceId"
            resolveParentPath={nestedParentPath}
          />
        }
      />
      <Route
        path="nodes/:nodeId/services/:serviceId/schemas/:schemaId"
        element={
          <AppDetailPage
            {...detailProps}
            detailEntityName="schemas"
            detailIdParam="schemaId"
            resolveParentPath={nestedParentPath}
          />
        }
      />
      <Route
        path="nodes/:nodeId/services/:serviceId/schemas/:schemaId/tables/:tableId"
        element={
          <AppDetailPage
            {...detailProps}
            detailEntityName="tables"
            detailIdParam="tableId"
            resolveParentPath={nestedParentPath}
          />
        }
      />
      <Route path="services" element={<Navigate to="../nodes" replace relative="path" />} />
      <Route path="schemas" element={<Navigate to="../nodes" replace relative="path" />} />
      <Route path="tables" element={<Navigate to="../nodes" replace relative="path" />} />
      <Route
        path="tables/:id"
        element={<AppDetailPage {...detailProps} detailEntityName="tables" detailIdParam="id" />}
      />
      <Route
        path="services/:id"
        element={<AppDetailPage {...detailProps} detailEntityName="services" detailIdParam="id" />}
      />
      <Route
        path="schemas/:id"
        element={<AppDetailPage {...detailProps} detailEntityName="schemas" detailIdParam="id" />}
      />
    </Routes>
  );
}
