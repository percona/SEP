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

import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';
import { AppCreatePage } from './AppCreatePage';
import type { RenderFormSlot } from './types';

const mockCreateTaskMutate = vi.fn();
const mockNavigate = vi.fn();
/** Flipped per test to cover the read-only (non-admin) rendering. */
let mockCanMutate = true;

vi.mock('@sep/api', () => ({
  useCreateAppTask: () => ({ mutate: mockCreateTaskMutate, isPending: false }),
  useCreateAppEntity: () => ({ mutate: vi.fn(), isPending: false }),
  useAuth: () => ({ isAdmin: mockCanMutate, canMutate: mockCanMutate }),
}));

vi.mock('react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router')>();
  return { ...actual, useNavigate: () => mockNavigate };
});

beforeEach(() => {
  mockCreateTaskMutate.mockReset();
  mockNavigate.mockReset();
  mockCanMutate = true;
});

const schema: AppSchema = {
  pluginName: 'checksums',
  display_name: 'Checksum',
  description: 'Test',
  capabilities: {},
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
  forms: [
    {
      title: 'Main',
      fields: [
        { type: 'string', name: 'title', label: 'Title' },
        { type: 'integer', name: 'count', label: 'Count' },
      ],
    },
  ],
} as unknown as AppSchema;

function renderPage(extra?: { renderCreateForm?: RenderFormSlot }) {
  return render(
    <SnackbarProvider>
      <MemoryRouter initialEntries={['/apps/checksums/new']}>
        <AppCreatePage schema={schema} pluginName="checksums" {...extra} />
      </MemoryRouter>
    </SnackbarProvider>,
  );
}

describe('AppCreatePage — renderCreateForm slot', () => {
  it('renders the default SchemaFormRenderer when no slot is supplied', () => {
    renderPage();
    // Default form body: the schema field renders, with the framework chrome.
    expect(screen.getByText('New Checksum')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toBeInTheDocument();
    expect(screen.queryByTestId('custom-form')).toBeNull();
  });

  it('replaces only the form body with the slot, keeping the page chrome', () => {
    const renderCreateForm: RenderFormSlot = () => <div data-testid="custom-form">custom body</div>;
    renderPage({ renderCreateForm });
    // Chrome preserved (title); default form body replaced.
    expect(screen.getByText('New Checksum')).toBeInTheDocument();
    expect(screen.getByTestId('custom-form')).toBeInTheDocument();
    expect(screen.queryByLabelText('Title')).toBeNull();
  });

  it('falls back to the default form when the slot returns a nullish value', () => {
    const renderCreateForm: RenderFormSlot = () => null;
    renderPage({ renderCreateForm });
    // null slot → default SchemaFormRenderer renders the schema fields.
    expect(screen.getByLabelText('Title')).toBeInTheDocument();
    expect(screen.queryByTestId('custom-form')).toBeNull();
  });

  it('wires the framework submit handler into the slot and coerces the payload', async () => {
    const user = userEvent.setup();
    // A custom slot that bypasses SchemaFormRenderer submits raw string values;
    // the page submit boundary must still coerce `count` to a number.
    const renderCreateForm: RenderFormSlot = ({ onSubmit, loading }) => (
      <button
        type="button"
        disabled={loading}
        onClick={() => onSubmit({ title: 'from-slot', count: '7' })}
      >
        Submit slot
      </button>
    );
    renderPage({ renderCreateForm });

    await user.click(screen.getByRole('button', { name: 'Submit slot' }));
    await waitFor(() => expect(mockCreateTaskMutate).toHaveBeenCalledTimes(1));
    expect(mockCreateTaskMutate).toHaveBeenCalledWith(
      { title: 'from-slot', count: 7 },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
  });
});

describe('AppCreatePage — post-create navigation', () => {
  const submitSlot: RenderFormSlot = ({ onSubmit }) => (
    <button type="button" onClick={() => onSubmit({ title: 'x' })}>
      Submit slot
    </button>
  );

  async function submitAndGetOnSuccess() {
    const user = userEvent.setup();
    renderPage({ renderCreateForm: submitSlot });
    await user.click(screen.getByRole('button', { name: 'Submit slot' }));
    await waitFor(() => expect(mockCreateTaskMutate).toHaveBeenCalledTimes(1));
    return mockCreateTaskMutate.mock.calls[0][1].onSuccess as (
      data: Record<string, unknown>,
    ) => void;
  }

  it('navigates to the new task detail with the warning in state when present', async () => {
    const onSuccess = await submitAndGetOnSuccess();
    const warning = { target: 'node1', service_type: 'mysql', message: 'fail', task_history_id: 7 };

    act(() => onSuccess({ name: 'my task', connectivity_warning: warning }));

    expect(mockNavigate).toHaveBeenCalledWith('../task/my%20task', {
      relative: 'path',
      state: { connectivityWarning: warning },
    });
  });

  it('navigates to the list (no state) when the create response carries no warning', async () => {
    const onSuccess = await submitAndGetOnSuccess();

    act(() => onSuccess({ name: 'my task' }));

    expect(mockNavigate).toHaveBeenCalledWith('..', { relative: 'path' });
  });
});

describe('AppCreatePage — write access', () => {
  it('renders the create form for a session that may mutate', () => {
    renderPage();

    expect(screen.getByRole('button', { name: 'Create Checksum' })).toBeInTheDocument();
    expect(screen.queryByTestId('app-create-read-only')).not.toBeInTheDocument();
  });

  it('renders the read-only guard instead of the create form for a non-admin', () => {
    mockCanMutate = false;
    renderPage();

    expect(screen.getByTestId('app-create-read-only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create Checksum' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Title')).not.toBeInTheDocument();
  });
});
