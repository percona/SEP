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

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useSnippetPluginSchema } from '@sep/framework';
import { SnippetDetailPage } from './SnippetDetailPage';
import { useSnippetDownload, useSnippetExecution, useSnippetHistory } from './hooks';

vi.mock('./hooks', () => ({
  useSnippetHistory: vi.fn(),
  useSnippetExecution: vi.fn(),
  useSnippetDownload: vi.fn(),
}));

vi.mock('@sep/framework', () => ({
  useSnippetPluginSchema: vi.fn(),
  snippetPluginSchemaPath: (filename: string) =>
    `/plugins/snippets/snippet/schema?snippet_filename=${encodeURIComponent(filename)}`,
  SchemaFormRenderer: () => <div>Execution form</div>,
  TaskHistoryTable: () => <div>History table</div>,
  TaskLogViewer: () => <div>Logs viewer</div>,
}));

const mockSchema = vi.mocked(useSnippetPluginSchema);
const mockHistory = vi.mocked(useSnippetHistory);
const mockExecution = vi.mocked(useSnippetExecution);
const mockDownload = vi.mocked(useSnippetDownload);

function renderAt(filename: string) {
  return render(
    <MemoryRouter initialEntries={[`/snippets/${filename}`]}>
      <Routes>
        <Route path="/snippets/:filename" element={<SnippetDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('SnippetDetailPage — Download button', () => {
  const mutate = vi.fn();
  const reset = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockSchema.mockReturnValue({
      data: {
        name: 'snippets',
        display_name: 'hello.sh',
        description: 'A friendly snippet',
        forms: [],
        list_view: { columns: [] },
      },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetPluginSchema>);
    mockHistory.mockReturnValue({
      data: { items: [], total: 0, offset: 0, limit: 50 },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetHistory>);
    mockExecution.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetExecution>);
    mockDownload.mockReturnValue({
      mutate,
      reset,
      isPending: false,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetDownload>);
  });

  it('fires the download mutation when the Download button is clicked', () => {
    renderAt('hello.sh');

    const button = screen.getByRole('button', { name: 'Download hello.sh' });
    fireEvent.click(button);

    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it('disables the Download button while the mutation is pending', () => {
    mockDownload.mockReturnValue({
      mutate,
      reset,
      isPending: true,
      isError: false,
      error: null,
    } as unknown as ReturnType<typeof useSnippetDownload>);

    renderAt('hello.sh');

    const button = screen.getByRole('button', { name: 'Download hello.sh' });
    expect(button).toBeDisabled();
  });

  it('surfaces a download error inline without crashing the page', () => {
    mockDownload.mockReturnValue({
      mutate,
      reset,
      isPending: false,
      isError: true,
      error: new Error('boom'),
    } as unknown as ReturnType<typeof useSnippetDownload>);

    renderAt('hello.sh');

    expect(screen.getByText(/Failed to download snippet:/)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
    // The rest of the page must still render — the error sits next to the
    // existing schema form, not in place of it.
    expect(screen.getByText('Execution form')).toBeInTheDocument();
  });
});
