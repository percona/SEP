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

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ListView } from '@sep/api';
import { SchemaListView, type RenderListColumnOverride } from './SchemaListView';

const listView: ListView = {
  columns: [
    { key: 'name', label: 'Name' },
    { key: 'status', label: 'Status', format: 'status' },
  ],
};

const rows = [
  { id: 1, name: 'alpha', status: 'completed' },
  { id: 2, name: 'beta', status: 'failed' },
];

describe('SchemaListView — renderListColumn override', () => {
  it('renders the override for a matching column and falls back to formatCellValue otherwise', () => {
    const renderListColumn: RenderListColumnOverride = ({ columnKey, value, row }) =>
      columnKey === 'status' ? (
        <span data-testid={`custom-status-${row.id}`}>custom:{String(value)}</span>
      ) : undefined;

    render(<SchemaListView listView={listView} data={rows} renderListColumn={renderListColumn} />);

    // status column → override
    expect(screen.getByTestId('custom-status-1')).toHaveTextContent('custom:completed');
    expect(screen.getByTestId('custom-status-2')).toHaveTextContent('custom:failed');
    // name column → no override returned (undefined) → default formatCellValue (plain text)
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
  });

  it('renders default formatCellValue for every column when no override is supplied', () => {
    render(<SchemaListView listView={listView} data={rows} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
    // status format renders a chip with the raw label text
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.queryByTestId('custom-status-1')).toBeNull();
  });

  it('never routes the actions column through the override', () => {
    const actionsListView: ListView = {
      columns: [
        { key: 'name', label: 'Name' },
        { key: 'actions', label: '', format: 'actions' },
      ],
    };
    const renderListColumn = vi.fn<RenderListColumnOverride>(() => <span>x</span>);
    render(
      <SchemaListView
        listView={actionsListView}
        data={rows}
        onDeleteRow={() => {}}
        renderListColumn={renderListColumn}
      />,
    );
    // override invoked only for the non-actions `name` column, never `actions`
    expect(renderListColumn).not.toHaveBeenCalledWith(
      expect.objectContaining({ columnKey: 'actions' }),
    );
    // delete control still rendered by the bespoke actions branch
    expect(screen.getAllByLabelText('Delete').length).toBe(rows.length);
  });
});
