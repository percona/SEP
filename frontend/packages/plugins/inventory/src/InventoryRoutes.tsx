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

import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import type { PluginSchema } from '@sep/api';
import { PluginDetailPage, PluginListPage } from '@sep/framework';
import { renderInventoryDetailChildren } from './InventoryPluginNavigation';
import { inventoryMountPrefix, pathToNestedInventoryParent } from './inventoryNestedPaths';

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
}: {
  schema: PluginSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  allowListEntityDelete: boolean;
}) {
  const { pathname } = useLocation();
  return (
    <PluginListPage
      schema={schema}
      pluginName="inventory"
      mockEntityItems={mockEntityItems}
      listOnly={false}
      hideCreate
      hideEntityTabs
      entityNameOverride="nodes"
      rowClickHref={(row) => `${pathname}/${String(row.id)}`}
      allowListEntityDelete={allowListEntityDelete}
    />
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
  schema: PluginSchema;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}) {
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
          />
        }
      />
      <Route
        path="nodes/:nodeId"
        element={
          <PluginDetailPage
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
          <PluginDetailPage
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
          <PluginDetailPage
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
          <PluginDetailPage
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
        element={<PluginDetailPage {...detailProps} detailEntityName="tables" detailIdParam="id" />}
      />
      <Route
        path="services/:id"
        element={
          <PluginDetailPage {...detailProps} detailEntityName="services" detailIdParam="id" />
        }
      />
      <Route
        path="schemas/:id"
        element={
          <PluginDetailPage {...detailProps} detailEntityName="schemas" detailIdParam="id" />
        }
      />
    </Routes>
  );
}
