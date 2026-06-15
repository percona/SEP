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
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { SnackbarProvider } from 'notistack';
import type { PluginSchema } from '@sep/api';
import { SchemaDrivenPlugin } from './SchemaDrivenPlugin';
import type { RenderFormSlot } from './types';

const mockUpdateMutate = vi.fn();

const schema: PluginSchema = {
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
} as unknown as PluginSchema;

// Stub sibling page modules so their @sep/api imports stay out of the graph;
// this test exercises only the SchemaDrivenPlugin → PluginEditPage threading.
vi.mock('./PluginListPage', () => ({ PluginListPage: () => <div>list</div> }));
vi.mock('./PluginDetailPage', () => ({
  PluginDetailPage: () => <div>detail</div>,
  pathToEntityList: () => '',
}));
vi.mock('./PluginSchedulePage', () => ({ PluginSchedulePage: () => <div>schedule</div> }));

vi.mock('@sep/api', () => ({
  usePluginSchema: () => ({ data: schema, isLoading: false, error: null }),
  usePluginEntityDetail: () => ({ data: { id: 5, label: 'n1' }, isLoading: false }),
  useUpdatePluginEntity: () => ({ mutate: mockUpdateMutate, isPending: false }),
  useCreatePluginEntity: () => ({ mutate: vi.fn(), isPending: false }),
  useCreatePluginTask: () => ({ mutate: vi.fn(), isPending: false }),
}));

function renderEdit(renderEditForm?: RenderFormSlot) {
  return render(
    <SnackbarProvider>
      <MemoryRouter initialEntries={['/nodes/5/edit']}>
        <SchemaDrivenPlugin pluginName="inventory" renderEditForm={renderEditForm} />
      </MemoryRouter>
    </SnackbarProvider>,
  );
}

describe('SchemaDrivenPlugin — renderEditForm slot', () => {
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
