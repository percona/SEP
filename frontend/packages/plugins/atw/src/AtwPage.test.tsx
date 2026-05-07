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

import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AtwPage } from './AtwPage';
import { useAtwCategories, useSnippetExecution, useSnippetSchema } from './hooks';

vi.mock('@sep/framework', () => ({
  SchemaFormRenderer: () => <div>Schema form</div>,
  buildSnippetExecutionFormPayload: (values: Record<string, unknown>) => values,
}));

vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock('./hooks', () => ({
  useAtwCategories: vi.fn(),
  useSnippetSchema: vi.fn(),
  useSnippetExecution: vi.fn(),
}));

const mockUseAtwCategories = vi.mocked(useAtwCategories);
const mockUseSnippetSchema = vi.mocked(useSnippetSchema);
const mockUseSnippetExecution = vi.mocked(useSnippetExecution);

describe('AtwPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseAtwCategories.mockReturnValue({
      data: [
        {
          category_root: 'MySQL',
          parent_category: 'PERFORMANCE_ISSUES',
          parent_category_label: 'Performance Issues',
          category: 'OVERALL_SLOWNESS',
          category_label: 'Overall Slowness',
          snippet_count: 1,
          snippets: [
            {
              name: 'diag/slow-query.sh',
              title: 'Slow Query Diagnostics',
              description: 'Collects slow-query and processlist data.',
              snippet_schema_url: '/plugins/snippets/diag%2Fslow-query.sh/schema',
              snippet_execute_url: '/plugins/snippets/diag%2Fslow-query.sh/execute',
              snippet_preview_url: '/plugins/snippets/diag%2Fslow-query.sh/script-preview',
            },
          ],
        },
      ],
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useAtwCategories>);
    mockUseSnippetSchema.mockReturnValue({
      data: null,
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetSchema>);
    mockUseSnippetExecution.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetExecution>);
  });

  it('renders the category browser controls', () => {
    render(<AtwPage />);

    expect(screen.getByRole('combobox', { name: 'Category' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Subcategory 1' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Subcategory 2' })).toBeTruthy();
    expect(screen.getByRole('combobox', { name: 'Snippet' })).toBeTruthy();
  });
});
