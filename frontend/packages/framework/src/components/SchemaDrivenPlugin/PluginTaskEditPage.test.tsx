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

import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import type { PluginSchema } from '@sep/api';
import { PluginTaskEditPage } from './PluginTaskEditPage';
import type { RenderFormSlot } from './types';

const mockUpdateTaskMutate = vi.fn();
const mockUsePluginTask = vi.fn();

vi.mock('@sep/api', () => ({
  useUpdatePluginTask: () => ({
    mutate: mockUpdateTaskMutate,
    isPending: false,
    isError: false,
    error: null,
  }),
  usePluginTask: (...args: unknown[]) => mockUsePluginTask(...args),
}));

const schema: PluginSchema = {
  pluginName: 'checksums',
  display_name: 'Checksum',
  description: 'Test',
  capabilities: {},
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
  forms: [
    {
      title: 'Main',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name' },
        { type: 'string', name: 'title', label: 'Title' },
        { type: 'integer', name: 'count', label: 'Count' },
      ],
    },
  ],
} as unknown as PluginSchema;

const STORED_TASK = {
  id: 1,
  name: 'check1',
  status: 'completed',
  data: { _form: { task_name: 'check1', title: 'hello', count: 7 } },
};

function renderAt(
  extra?: { renderEditForm?: RenderFormSlot },
  path = '/plugins/checksums/task/check1/edit',
) {
  return render(
    <SnackbarProvider>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/plugins/:plugin/task/:id/edit"
            element={<PluginTaskEditPage schema={schema} pluginName="checksums" {...extra} />}
          />
          <Route path="/plugins/:plugin/task/:id" element={<div>detail page</div>} />
        </Routes>
      </MemoryRouter>
    </SnackbarProvider>,
  );
}

beforeEach(() => {
  mockUpdateTaskMutate.mockReset();
  mockUsePluginTask.mockReset();
});

describe('PluginTaskEditPage', () => {
  it('prefills the editable fields from the stored create-form body', () => {
    mockUsePluginTask.mockReturnValue({ data: STORED_TASK, isLoading: false });

    renderAt();

    expect(screen.getByText('Edit Checksum: check1')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('hello');
  });

  it('renders the task name read-only (no editable task_name input)', () => {
    mockUsePluginTask.mockReturnValue({ data: STORED_TASK, isLoading: false });

    renderAt();

    // The immutable identity is shown in the header, never as an editable field.
    expect(screen.queryByLabelText('Task Name')).toBeNull();
    expect(screen.getByText('Edit Checksum: check1')).toBeInTheDocument();
  });

  it('submits coerced values and pins task_name to the route id', async () => {
    mockUsePluginTask.mockReturnValue({ data: STORED_TASK, isLoading: false });
    // A slot bypassing SchemaFormRenderer submits raw string values and omits
    // task_name; the page coerces `count` and re-asserts the original name.
    const renderEditForm: RenderFormSlot = ({ onSubmit, loading }) => (
      <button
        type="button"
        disabled={loading}
        onClick={() => onSubmit({ title: 'changed', count: '9' })}
      >
        Submit slot
      </button>
    );

    renderAt({ renderEditForm });
    await userEvent.click(screen.getByRole('button', { name: 'Submit slot' }));

    await waitFor(() => expect(mockUpdateTaskMutate).toHaveBeenCalledTimes(1));
    expect(mockUpdateTaskMutate).toHaveBeenCalledWith(
      { taskId: 'check1', values: { title: 'changed', count: 9, task_name: 'check1' } },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
  });

  it('keeps task_name pinned even when the submitted body carries a different name', async () => {
    mockUsePluginTask.mockReturnValue({ data: STORED_TASK, isLoading: false });
    const renderEditForm: RenderFormSlot = ({ onSubmit }) => (
      <button type="button" onClick={() => onSubmit({ task_name: 'renamed', title: 'x' })}>
        Submit slot
      </button>
    );

    renderAt({ renderEditForm });
    await userEvent.click(screen.getByRole('button', { name: 'Submit slot' }));

    await waitFor(() => expect(mockUpdateTaskMutate).toHaveBeenCalledTimes(1));
    const [{ values }] = mockUpdateTaskMutate.mock.calls[0];
    expect(values.task_name).toBe('check1');
  });

  it('navigates back to the task detail on a successful update', async () => {
    mockUsePluginTask.mockReturnValue({ data: STORED_TASK, isLoading: false });
    mockUpdateTaskMutate.mockImplementation((_vars, opts) => opts.onSuccess?.());
    const renderEditForm: RenderFormSlot = ({ onSubmit }) => (
      <button type="button" onClick={() => onSubmit({ title: 'x' })}>
        Submit slot
      </button>
    );

    renderAt({ renderEditForm });
    await userEvent.click(screen.getByRole('button', { name: 'Submit slot' }));

    await waitFor(() => expect(screen.getByText('detail page')).toBeInTheDocument());
  });

  it('redirects to detail without crashing when the task has no stored form', () => {
    mockUsePluginTask.mockReturnValue({
      data: { id: 1, name: 'check1', status: 'completed', data: { meta: {} } },
      isLoading: false,
    });

    renderAt();

    expect(screen.getByText('detail page')).toBeInTheDocument();
    expect(screen.queryByText('Edit Checksum: check1')).toBeNull();
  });
});
