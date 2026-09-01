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
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router';
import { SnackbarProvider } from 'notistack';
import type { AppSchema } from '@sep/api';
import { SchemaDrivenApp } from './SchemaDrivenApp';
import type { RenderFormSlot } from './types';

const mockUpdateMutate = vi.fn();

const schema: AppSchema = {
  pluginName: 'inventory',
  display_name: 'Inventory',
  entities: [
    {
      name: 'nodes',
      display_name: 'Nodes',
      forms: [{ title: 'Main', fields: [{ type: 'string', name: 'label', label: 'Label' }] }],
      list_view: { columns: [{ key: 'label', label: 'Label' }] },
    },
  ],
} as unknown as AppSchema;

// Single-entity (task-style) schema for the task/:id/edit branch.
const taskSchema: AppSchema = {
  pluginName: 'checksums',
  display_name: 'Checksum',
  forms: [
    {
      title: 'Main',
      fields: [
        { type: 'string', name: 'task_name', label: 'Task Name' },
        { type: 'string', name: 'title', label: 'Title' },
      ],
    },
  ],
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
} as unknown as AppSchema;

const backupsSchema: AppSchema = {
  name: 'mysql_backups',
  display_name: 'MySQL Backups',
  forms: [{ title: 'Main', fields: [{ type: 'string', name: 'name', label: 'Name' }] }],
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
  related_apps: [
    {
      app_key: 'mysql_backups/restore',
      label: 'Restore',
      route_segment: 'restores',
    },
  ],
} as unknown as AppSchema;

const restoreSchema: AppSchema = {
  name: 'mysql_backups_restore',
  display_name: 'Restore',
  forms: [{ title: 'Main', fields: [{ type: 'string', name: 'name', label: 'Name' }] }],
  list_view: { columns: [{ key: 'name', label: 'Name' }] },
} as unknown as AppSchema;

const taskRecord = {
  id: 1,
  name: 'check1',
  data: { _form: { task_name: 'check1', title: 'hello' } },
};

// Schema the mocked useAppSchema serves; per-test override, reset after each.
let activeSchema: AppSchema = schema;

// Stub sibling page modules so their @sep/api imports stay out of the graph;
// this test exercises only the SchemaDrivenApp → edit-page threading.
vi.mock('./AppListPage', () => ({
  AppListPage: ({ pluginName }: { pluginName: string }) => <div>list:{pluginName}</div>,
}));
vi.mock('./AppDetailPage', () => ({
  AppDetailPage: () => <div>detail</div>,
  pathToEntityList: () => '',
}));
vi.mock('./AppSchedulePage', () => ({ AppSchedulePage: () => <div>schedule</div> }));

/** Flipped per test to cover the read-only (non-admin) rendering. */
let mockCanMutate = true;

vi.mock('@sep/api', () => ({
  useAuth: () => ({ isAdmin: mockCanMutate, canMutate: mockCanMutate }),
  useAppSchema: (pluginName: string) => {
    if (pluginName === 'mysql_backups/restore') {
      return { data: restoreSchema, isLoading: false, error: null };
    }
    return { data: activeSchema, isLoading: false, error: null };
  },
  useAppEntityDetail: () => ({ data: { id: 5, label: 'n1' }, isLoading: false }),
  useUpdateAppEntity: () => ({ mutate: mockUpdateMutate, isPending: false }),
  useCreateAppEntity: () => ({ mutate: vi.fn(), isPending: false }),
  useCreateAppTask: () => ({ mutate: vi.fn(), isPending: false }),
  useAppTask: () => ({ data: taskRecord, isLoading: false }),
  useUpdateAppTask: () => ({ mutate: vi.fn(), isPending: false, isError: false, error: null }),
}));

afterEach(() => {
  activeSchema = schema;
  mockCanMutate = true;
});

function renderEdit(renderEditForm?: RenderFormSlot) {
  return render(
    <SnackbarProvider>
      <MemoryRouter initialEntries={['/nodes/5/edit']}>
        <SchemaDrivenApp pluginName="inventory" renderEditForm={renderEditForm} />
      </MemoryRouter>
    </SnackbarProvider>,
  );
}

describe('SchemaDrivenApp — renderEditForm slot', () => {
  it('renders the default form body when no slot is supplied', () => {
    renderEdit();
    expect(screen.getByText('Edit Nodes #5')).toBeInTheDocument();
    expect(screen.getByLabelText('Label')).toBeInTheDocument();
    expect(screen.queryByTestId('custom-edit-form')).toBeNull();
  });

  it('replaces only the form body with the slot, keeping chrome and mutation wiring', async () => {
    const user = userEvent.setup();
    const renderEditForm: RenderFormSlot = ({ onSubmit, defaultValues }) => (
      <button type="button" onClick={() => onSubmit({ ...defaultValues, label: 'edited' })}>
        Save slot
      </button>
    );
    renderEdit(renderEditForm);

    // Chrome preserved; default form body replaced by the slot.
    expect(screen.getByText('Edit Nodes #5')).toBeInTheDocument();
    expect(screen.queryByLabelText('Label')).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Save slot' }));
    await waitFor(() => expect(mockUpdateMutate).toHaveBeenCalledTimes(1));
    expect(mockUpdateMutate).toHaveBeenCalledWith(
      { id: '5', values: expect.objectContaining({ label: 'edited' }) },
      expect.objectContaining({ onSuccess: expect.any(Function), onError: expect.any(Function) }),
    );
  });
});

describe('SchemaDrivenApp — single-entity task edit route', () => {
  it('renders AppTaskEditPage at task/:id/edit, prefilled from the stored form', () => {
    activeSchema = taskSchema;
    render(
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/task/check1/edit']}>
          <SchemaDrivenApp pluginName="checksums" />
        </MemoryRouter>
      </SnackbarProvider>,
    );

    expect(screen.getByText('Edit Checksum: check1')).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toHaveValue('hello');
    // task_name stays immutable: no editable name input is rendered.
    expect(screen.queryByLabelText('Task Name')).toBeNull();
  });
});

describe('SchemaDrivenApp — related_apps routing', () => {
  function renderBackupsPlugin(pathname: string) {
    return render(
      <SnackbarProvider>
        <MemoryRouter initialEntries={[pathname]}>
          <Routes>
            <Route
              path="/apps/mysql_backups/*"
              element={
                <SchemaDrivenApp pluginName="mysql_backups" routeBase="/apps/mysql_backups" />
              }
            />
          </Routes>
        </MemoryRouter>
      </SnackbarProvider>,
    );
  }

  it('does not render the related-app tab bar when related_apps is absent', () => {
    activeSchema = taskSchema;
    render(
      <SnackbarProvider>
        <MemoryRouter initialEntries={['/']}>
          <SchemaDrivenApp pluginName="checksums" routeBase="/apps/checksums" />
        </MemoryRouter>
      </SnackbarProvider>,
    );

    expect(screen.getByText('list:checksums')).toBeInTheDocument();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('renders the tab bar and parent list on the parent route', () => {
    activeSchema = backupsSchema;
    renderBackupsPlugin('/apps/mysql_backups');

    expect(screen.getByRole('tab', { name: 'MySQL Backups' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tab', { name: 'Restore' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByText('list:mysql_backups')).toBeInTheDocument();
  });

  it('mounts a nested SchemaDrivenApp for a related route segment', () => {
    activeSchema = backupsSchema;
    renderBackupsPlugin('/apps/mysql_backups/restores');

    expect(screen.getByRole('tab', { name: 'Restore' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('list:mysql_backups/restore')).toBeInTheDocument();
    expect(screen.queryByText('list:mysql_backups')).toBeNull();
  });
});

describe('SchemaDrivenApp — write access', () => {
  it('renders the entity edit form for a session that may mutate', () => {
    renderEdit();

    expect(screen.queryByTestId('app-entity-edit-read-only')).not.toBeInTheDocument();
    expect(screen.getByText(/Edit Nodes #5/)).toBeInTheDocument();
  });

  it('renders the read-only guard instead of the entity edit form for a non-admin', () => {
    mockCanMutate = false;
    renderEdit();

    expect(screen.getByTestId('app-entity-edit-read-only')).toBeInTheDocument();
    expect(screen.queryByText(/Edit Nodes #5/)).not.toBeInTheDocument();
  });
});
