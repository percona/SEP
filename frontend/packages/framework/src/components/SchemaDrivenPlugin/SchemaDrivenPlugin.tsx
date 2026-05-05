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

import { useMemo, type ReactNode } from 'react';
import { Routes, Route, Navigate, useNavigate, useParams } from 'react-router-dom';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import Typography from '@mui/material/Typography';
import IconButton from '@mui/material/IconButton';
import Skeleton from '@mui/material/Skeleton';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import { useSnackbar } from 'notistack';
import {
  usePluginSchema,
  usePluginEntityDetail,
  useUpdatePluginEntity,
  type PluginEntitySchema,
  type PluginSchema,
} from '@sep/api';
import { SchemaFormRenderer } from '../SchemaFormRenderer';
import { PluginListPage } from './PluginListPage';
import { PluginCreatePage } from './PluginCreatePage';
import { PluginDetailPage } from './PluginDetailPage';
import { PluginSchedulePage } from './PluginSchedulePage';

interface SchemaDrivenPluginProps {
  pluginName: string;
  mockSchema?: PluginSchema;
  mockTasks?: Record<string, unknown>[];
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
  /** When true, only the list table is shown (no create, detail, or edit routes). */
  listOnly?: boolean;
  /**
   * Browse mode: list + read-only detail (and optional ``renderEntityDetailChildren``),
   * without create / edit / delete routes on detail chrome. List row delete is separate
   * (see ``allowListEntityDelete``).
   */
  browseOnly?: boolean;
  /** Keys to hide from the generic detail field dump (nested relations, etc.). */
  suppressDetailKeys?: string[];
  /** Hide multi-entity tab bar (e.g. inventory uses breadcrumbs instead). */
  hideEntityTabs?: boolean;
  /**
   * When true, entity list tables that declare an ``actions`` column show a per-row delete
   * control (inventory uses this with browse-only detail chrome).
   */
  allowListEntityDelete?: boolean;
  renderEntityDetailChildren?: (args: {
    entityName: string;
    record: Record<string, unknown>;
    schema: PluginSchema;
    pathname: string;
    pluginName: string;
    mockEntityItems?: Record<string, Record<string, unknown>[]>;
    allowListEntityDelete?: boolean;
  }) => ReactNode;
}

function PluginEditPage({
  schema,
  pluginName,
  mockEntityItems,
}: {
  schema: PluginSchema;
  pluginName: string;
  mockEntityItems?: Record<string, Record<string, unknown>[]>;
}) {
  const navigate = useNavigate();
  const { entityName, id } = useParams<{ entityName?: string; id: string }>();
  const entitySchema = useMemo(
    () => schema.entities?.find((e: PluginEntitySchema) => e.name === entityName),
    [schema.entities, entityName],
  );
  const multi = Boolean(schema.entities?.length && entityName && entitySchema);

  const { enqueueSnackbar } = useSnackbar();
  const updateEntity = useUpdatePluginEntity(
    pluginName,
    entityName ?? '',
    multi ? mockEntityItems?.[entityName!] : undefined,
  );

  const { data: item, isLoading } = usePluginEntityDetail(
    pluginName,
    entityName ?? '',
    id,
    multi ? mockEntityItems?.[entityName!] : undefined,
    { enabled: multi && Boolean(id) },
  );

  const title = entitySchema?.displayName ?? schema.displayName;
  const sections = entitySchema?.forms ?? schema.forms!;

  const handleSubmit = (data: Record<string, unknown>) => {
    if (!id || !multi) {
      return;
    }
    updateEntity.mutate(
      { id, values: data },
      {
        onSuccess: () => {
          enqueueSnackbar(`${title} updated`, { variant: 'success' });
          navigate('..', { relative: 'path' });
        },
        onError: (error: unknown) => {
          const message = error instanceof Error ? error.message : 'Failed to update';
          enqueueSnackbar(message, { variant: 'error' });
        },
      },
    );
  };

  if (!multi || !entitySchema) {
    return (
      <Box sx={{ py: 2 }}>
        <Typography color="text.secondary">
          Edit is only available for multi-entity plugins.
        </Typography>
      </Box>
    );
  }

  if (isLoading) {
    return (
      <Box>
        <Skeleton variant="text" width={300} height={40} />
        <Skeleton variant="rectangular" height={200} sx={{ mt: 2 }} />
      </Box>
    );
  }

  if (!item) {
    return (
      <Box sx={{ py: 2 }}>
        <Typography variant="h5">Not found</Typography>
      </Box>
    );
  }

  const defaultValues = item as Record<string, unknown>;

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 3 }}>
        <IconButton onClick={() => navigate('..', { relative: 'path' })}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h4">
          Edit {title} #{id}
        </Typography>
      </Box>

      <SchemaFormRenderer
        sections={sections}
        onSubmit={handleSubmit}
        loading={updateEntity.isPending}
        submitLabel={`Save ${title}`}
        defaultValues={defaultValues}
      />
    </Box>
  );
}

export function SchemaDrivenPlugin({
  pluginName,
  mockSchema,
  mockTasks,
  mockEntityItems,
  listOnly = false,
  browseOnly = false,
  suppressDetailKeys,
  hideEntityTabs = false,
  allowListEntityDelete = false,
  renderEntityDetailChildren,
}: SchemaDrivenPluginProps) {
  const { data: schema, isLoading, error } = usePluginSchema(pluginName, mockSchema);
  const showMutationRoutes = !listOnly && !browseOnly;
  const showDetailRoutes = !listOnly;

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
        <Typography color="error">Failed to load plugin schema: {error.message}</Typography>
      </Box>
    );
  }

  if (!schema) {
    return null;
  }

  if (schema.entities?.length) {
    const first = schema.entities[0].name;
    return (
      <Routes>
        <Route index element={<Navigate to={first} replace />} />
        <Route
          path=":entityName"
          element={
            <PluginListPage
              schema={schema}
              pluginName={pluginName}
              mockEntityItems={mockEntityItems}
              listOnly={listOnly}
              hideCreate={browseOnly && !listOnly}
              hideEntityTabs={hideEntityTabs}
              allowListEntityDelete={allowListEntityDelete}
            />
          }
        />
        {showMutationRoutes && (
          <>
            <Route
              path=":entityName/new"
              element={
                <PluginCreatePage
                  schema={schema}
                  pluginName={pluginName}
                  mockEntityItems={mockEntityItems}
                />
              }
            />
            <Route
              path=":entityName/:id/edit"
              element={
                <PluginEditPage
                  schema={schema}
                  pluginName={pluginName}
                  mockEntityItems={mockEntityItems}
                />
              }
            />
          </>
        )}
        {showDetailRoutes && (
          <Route
            path=":entityName/:id"
            element={
              <PluginDetailPage
                schema={schema}
                pluginName={pluginName}
                mockEntityItems={mockEntityItems}
                browseOnly={browseOnly}
                suppressDetailKeys={suppressDetailKeys}
                renderEntityDetailChildren={renderEntityDetailChildren}
                allowListEntityDelete={allowListEntityDelete}
              />
            }
          />
        )}
      </Routes>
    );
  }

  return (
    <Routes>
      <Route
        index
        element={
          <PluginListPage
            schema={schema}
            pluginName={pluginName}
            mockTasks={mockTasks}
            mockEntityItems={mockEntityItems}
            listOnly={listOnly}
            hideCreate={browseOnly && !listOnly}
          />
        }
      />
      {showMutationRoutes && (
        <Route
          path="new"
          element={
            <PluginCreatePage schema={schema} pluginName={pluginName} mockTasks={mockTasks} />
          }
        />
      )}
      {/* Schedule route is only registered when the plugin schema opts in;
          otherwise direct navigation to `/plugins/<name>/schedule` would
          show the panel even though the entry-point buttons (which gate on
          the same capability) are hidden. */}
      {schema.capabilities?.scheduling && (
        <Route path="schedule" element={<PluginSchedulePage pluginName={pluginName} />} />
      )}
      {showDetailRoutes && (
        <Route
          path="task/:id/*"
          element={
            <PluginDetailPage
              schema={schema}
              pluginName={pluginName}
              mockTasks={mockTasks}
              browseOnly={browseOnly}
              suppressDetailKeys={suppressDetailKeys}
              renderEntityDetailChildren={renderEntityDetailChildren}
              allowListEntityDelete={allowListEntityDelete}
            />
          }
        />
      )}
    </Routes>
  );
}
