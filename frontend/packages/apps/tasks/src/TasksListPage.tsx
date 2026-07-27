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

import { useState } from 'react';
import { Alert, Box, CircularProgress, Typography } from '@mui/material';
import { useNavigate } from 'react-router';
import { DEFAULT_APP_LIST_LIMIT, DEFAULT_APP_LIST_OFFSET } from '@sep/api';
import { SchemaListView } from '@sep/framework';
import { useTasksList, useTasksAppSchema } from './hooks';

export function TasksListPage() {
  const navigate = useNavigate();
  const [listPage, setListPage] = useState({
    offset: DEFAULT_APP_LIST_OFFSET,
    limit: DEFAULT_APP_LIST_LIMIT,
  });
  const { data: schema, isLoading: schemaLoading, error: schemaError } = useTasksAppSchema();
  const {
    data: listResult,
    isLoading: listLoading,
    error: listError,
  } = useTasksList({
    enabled: Boolean(schema?.list_view),
    offset: listPage.offset,
    limit: listPage.limit,
  });

  const rows = listResult?.items ?? [];
  const listPagination = listResult?.pagination ?? null;

  if (schemaLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (schemaError || !schema?.list_view) {
    return (
      <Alert severity="error">
        {schemaError instanceof Error ? schemaError.message : 'Failed to load Task Manager schema.'}
      </Alert>
    );
  }

  if (listError) {
    return (
      <Alert severity="error">
        {listError instanceof Error ? listError.message : 'Failed to load tasks.'}
      </Alert>
    );
  }

  const listView = schema.list_view;

  return (
    <Box>
      <Box sx={{ mb: 3 }}>
        <Typography variant="h4" component="h1">
          {schema.display_name}
        </Typography>
        {schema.description ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {schema.description}
          </Typography>
        ) : null}
      </Box>

      <SchemaListView
        listView={listView}
        data={rows as unknown as Record<string, unknown>[]}
        isLoading={listLoading}
        pagination={
          listPagination
            ? {
                total: listPagination.total,
                offset: listPagination.offset,
                limit: listPagination.limit,
                onChange: setListPage,
              }
            : null
        }
        onRowClick={(row) => {
          const name = row.name;
          if (name !== undefined && name !== null) {
            navigate(encodeURIComponent(String(name)));
          }
        }}
      />
    </Box>
  );
}
