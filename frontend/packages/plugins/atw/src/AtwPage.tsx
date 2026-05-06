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
import { useNavigate } from 'react-router-dom';
import { SchemaFormRenderer, buildSnippetExecutionFormPayload } from '@sep/framework';
import { useAtwCategories, useSnippetExecution, useSnippetSchema } from './hooks';
import type { AtwCategoryListing, AtwSnippetSummary } from './types';

export function AtwPage() {
  const navigate = useNavigate();
  const [selectedCategory1, setSelectedCategory1] = useState<string>('');
  const [selectedSubcategory1, setSelectedSubcategory1] = useState<string>('');
  const [selectedSubcategory2, setSelectedSubcategory2] = useState<string>('');
  const [selectedSnippet, setSelectedSnippet] = useState<string>('');

  const categoriesQuery = useAtwCategories();

  const category1Options = useMemo(() => {
    const listing = categoriesQuery.data ?? [];
    return Array.from(new Set(listing.map((item: AtwCategoryListing) => item.category_root)));
  }, [categoriesQuery.data]);

  const subcategory1Options = useMemo(() => {
    const listing = categoriesQuery.data ?? [];
    const seen = new Set<string>();
    return listing
      .filter((item: AtwCategoryListing) => item.category_root === selectedCategory1)
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
  }, [categoriesQuery.data, selectedCategory1]);

  const subcategory2Options = useMemo(() => {
    const listing = categoriesQuery.data ?? [];
    return listing.filter(
      (item: AtwCategoryListing) =>
        item.category_root === selectedCategory1 && item.parent_category === selectedSubcategory1,
    );
  }, [categoriesQuery.data, selectedCategory1, selectedSubcategory1]);

  const selectedSubcategory2Row = useMemo<AtwCategoryListing | null>(
    () =>
      subcategory2Options.find(
        (item: AtwCategoryListing) => item.category === selectedSubcategory2,
      ) ?? null,
    [subcategory2Options, selectedSubcategory2],
  );

  const selectedSnippetRow = useMemo<AtwSnippetSummary | null>(
    () =>
      selectedSubcategory2Row?.snippets.find(
        (snippet: AtwSnippetSummary) => snippet.name === selectedSnippet,
      ) ?? null,
    [selectedSubcategory2Row, selectedSnippet],
  );

  const schemaQuery = useSnippetSchema(selectedSnippetRow?.snippet_schema_url ?? null);
  const executionMutation = useSnippetExecution(selectedSnippetRow?.snippet_execute_url ?? null);

  const submitError = executionMutation.isError
    ? (executionMutation.error?.message ?? 'Execution failed')
    : null;

  const handleSubmit = (values: Record<string, unknown>) => {
    if (!selectedSnippetRow) {
      return;
    }

    executionMutation.mutate(buildSnippetExecutionFormPayload(values), {
      onSuccess: () => {
        navigate(`/snippets/${encodeURIComponent(selectedSnippetRow.name)}`);
      },
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
        Collect Diagnostic Data
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Select an issue category, then run the matching troubleshooting snippet.
      </Typography>

      <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} sx={{ mb: 3 }}>
        <FormControl fullWidth>
          <InputLabel id="atw-category1-label">Category</InputLabel>
          <Select
            labelId="atw-category1-label"
            value={selectedCategory1}
            label="Category"
            onChange={(event: SelectChangeEvent) => {
              setSelectedCategory1(event.target.value);
              setSelectedSubcategory1('');
              setSelectedSubcategory2('');
              setSelectedSnippet('');
            }}
          >
            {category1Options.map((option) => (
              <MenuItem key={option} value={option}>
                {option}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth>
          <InputLabel id="atw-category2-label">Subcategory 1</InputLabel>
          <Select
            labelId="atw-category2-label"
            value={selectedSubcategory1}
            label="Subcategory 1"
            disabled={!selectedCategory1}
            onChange={(event: SelectChangeEvent) => {
              setSelectedSubcategory1(event.target.value);
              setSelectedSubcategory2('');
              setSelectedSnippet('');
            }}
          >
            {subcategory1Options.map((option: { value: string; label: string }) => (
              <MenuItem key={option.value} value={option.value}>
                {option.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth disabled={!selectedCategory1 || !selectedSubcategory1}>
          <InputLabel id="atw-category3-label">Subcategory 2</InputLabel>
          <Select
            labelId="atw-category3-label"
            value={selectedSubcategory2}
            label="Subcategory 2"
            onChange={(event: SelectChangeEvent) => {
              setSelectedSubcategory2(event.target.value);
              setSelectedSnippet('');
            }}
          >
            {subcategory2Options.map((category: AtwCategoryListing) => (
              <MenuItem key={category.category} value={category.category}>
                {category.category_label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl fullWidth disabled={!selectedCategory1 || !selectedSubcategory2Row}>
          <InputLabel id="atw-snippet-label">Snippet</InputLabel>
          <Select
            labelId="atw-snippet-label"
            value={selectedSnippet}
            label="Snippet"
            onChange={(event: SelectChangeEvent) => {
              setSelectedSnippet(event.target.value);
            }}
          >
            {(selectedSubcategory2Row?.snippets ?? []).map((snippet) => (
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
