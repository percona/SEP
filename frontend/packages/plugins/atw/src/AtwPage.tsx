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

import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material';
import type { SelectChangeEvent } from '@mui/material/Select';
import { SchemaFormRenderer } from '@sep/framework';
import { useAtwCategories, useSnippetExecution, useSnippetSchema } from './hooks';
import type { AtwCategoryListing, AtwSnippetSummary } from './types';

const EXECUTION_RESERVED_NAMES = new Set(['executor_host', 'sudo', 'script_preview']);

export function AtwPage() {
  const [selectedTechnology, setSelectedTechnology] = useState<string>('');
  const [selectedParent, setSelectedParent] = useState<string>('');
  const [selectedCategory, setSelectedCategory] = useState<string>('');
  const [selectedSnippet, setSelectedSnippet] = useState<string>('');

  const categoriesQuery = useAtwCategories();

  const parentOptions = useMemo(() => {
    const listing = categoriesQuery.data ?? [];
    const seen = new Set<string>();
    return listing
      .filter((item: AtwCategoryListing) => {
        if (seen.has(item.parent_category)) {
          return false;
        }
        seen.add(item.parent_category);
        return true;
      })
      .map((item: AtwCategoryListing) => ({
        value: item.parent_category,
        label: item.parent_category_label,
      }));
  }, [categoriesQuery.data]);

  const categoriesForParent = useMemo(() => {
    const listing = categoriesQuery.data ?? [];
    return listing.filter((item: AtwCategoryListing) => item.parent_category === selectedParent);
  }, [categoriesQuery.data, selectedParent]);

  const selectedCategoryRow = useMemo<AtwCategoryListing | null>(
    () =>
      categoriesForParent.find((item: AtwCategoryListing) => item.category === selectedCategory) ??
      null,
    [categoriesForParent, selectedCategory],
  );

  const selectedSnippetRow = useMemo<AtwSnippetSummary | null>(
    () =>
      selectedCategoryRow?.snippets.find(
        (snippet: AtwSnippetSummary) => snippet.name === selectedSnippet,
      ) ?? null,
    [selectedCategoryRow, selectedSnippet],
  );

  const schemaQuery = useSnippetSchema(selectedSnippetRow?.snippet_schema_url ?? null);
  const executionMutation = useSnippetExecution(selectedSnippetRow?.snippet_execute_url ?? null);

  const submitError = executionMutation.isError
    ? (executionMutation.error?.message ?? 'Execution failed')
    : null;

  const successMessage =
    executionMutation.isSuccess && executionMutation.data
      ? `Snippet queued as ${executionMutation.data.task_name}.`
      : null;

  const handleSubmit = (values: Record<string, unknown>) => {
    const args: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (EXECUTION_RESERVED_NAMES.has(key)) {
        continue;
      }
      if (value === '' || value === undefined) {
        continue;
      }
      args[key] = value;
    }
    executionMutation.mutate({
      executor_host: String(values.executor_host ?? ''),
      sudo: Boolean(values.sudo ?? false),
      args,
    });
  };

  if (categoriesQuery.isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (categoriesQuery.error) {
    return (
      <Alert severity="error">Failed to load ATW categories: {categoriesQuery.error.message}</Alert>
    );
  }

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Ask Know The World
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Select an issue category, then run the matching troubleshooting snippet.
      </Typography>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 3 }}>
        <FormControl fullWidth>
          <InputLabel id="atw-technology-label">Category</InputLabel>
          <Select
            labelId="atw-technology-label"
            value={selectedTechnology}
            label="Category"
            onChange={(event: SelectChangeEvent) => {
              setSelectedTechnology(event.target.value);
              setSelectedParent('');
              setSelectedCategory('');
              setSelectedSnippet('');
            }}
          >
            <MenuItem value="MySQL">MySQL</MenuItem>
          </Select>
        </FormControl>

        <FormControl fullWidth>
          <InputLabel id="atw-parent-label">Parent Category</InputLabel>
          <Select
            labelId="atw-parent-label"
            value={selectedParent}
            label="Parent Category"
            disabled={selectedTechnology !== 'MySQL'}
            onChange={(event: SelectChangeEvent) => {
              setSelectedParent(event.target.value);
              setSelectedCategory('');
              setSelectedSnippet('');
            }}
          >
            {parentOptions.map((option: { value: string; label: string }) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth disabled={selectedTechnology !== 'MySQL' || !selectedParent}>
          <InputLabel id="atw-category-label">Category</InputLabel>
          <Select
            labelId="atw-category-label"
            value={selectedCategory}
            label="Category"
            onChange={(event: SelectChangeEvent) => {
              setSelectedCategory(event.target.value);
              setSelectedSnippet('');
            }}
          >
            {categoriesForParent.map((category: AtwCategoryListing) => (
              <MenuItem key={category.category} value={category.category}>
                {category.category_label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth disabled={selectedTechnology !== 'MySQL' || !selectedCategoryRow}>
          <InputLabel id="atw-snippet-label">Snippet</InputLabel>
          <Select
            labelId="atw-snippet-label"
            value={selectedSnippet}
            label="Snippet"
            onChange={(event: SelectChangeEvent) => {
              setSelectedSnippet(event.target.value);
            }}
          >
            {(selectedCategoryRow?.snippets ?? []).map((snippet) => (
              <MenuItem key={snippet.name} value={snippet.name}>
                {snippet.title}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      </Stack>

      {selectedSnippetRow && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {selectedSnippetRow.description}
        </Typography>
      )}

      {successMessage && (
        <Alert severity="success" sx={{ mb: 2 }}>
          {successMessage}
        </Alert>
      )}

      {selectedSnippetRow && schemaQuery.isLoading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}

      {selectedSnippetRow && schemaQuery.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Failed to load snippet form: {schemaQuery.error.message}
        </Alert>
      )}

      {selectedSnippetRow && schemaQuery.data && (
        <SchemaFormRenderer
          sections={schemaQuery.data.forms}
          onSubmit={handleSubmit}
          submitLabel="Execute"
          loading={executionMutation.isPending}
          submitError={submitError}
        />
      )}
    </Box>
  );
}
