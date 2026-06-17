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
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FormSection } from '@sep/api';

// Replace the framework with a thin renderer that drives a real react-hook-form
// context and invokes the override per source field — enough to exercise
// ArchiveForm's mode wiring and the toggle's clear-on-switch behaviour without
// pulling in the full SchemaFormRenderer dependency tree. The inventory hooks
// return no options (the toggle test does not depend on inventory data).
vi.mock('@sep/framework', async () => {
  const rhf = await import('react-hook-form');
  const MockSchemaFormRenderer = ({
    sections,
    onSubmit,
    defaultValues,
    renderField,
  }: {
    sections: { fields: { name: string }[] }[];
    onSubmit: (data: Record<string, unknown>) => void;
    defaultValues?: Record<string, unknown>;
    renderField?: (args: { field: { name: string }; renderDefault: () => null }) => unknown;
  }) => {
    const methods = rhf.useForm({ defaultValues });
    const fields = sections.flatMap((s) => s.fields);
    return (
      <rhf.FormProvider {...methods}>
        <form onSubmit={methods.handleSubmit((v) => onSubmit(v))}>
          {fields.map((f) => {
            const node = renderField?.({ field: f, renderDefault: () => null });
            return <div key={f.name}>{node === undefined ? null : (node as React.ReactNode)}</div>;
          })}
          <button type="submit">Submit</button>
          <output data-testid="values">{JSON.stringify(methods.watch())}</output>
        </form>
      </rhf.FormProvider>
    );
  };
  return {
    useSchemas: () => ({ data: [], isLoading: false }),
    useTables: () => ({ data: [], isLoading: false }),
    SchemaFormRenderer: MockSchemaFormRenderer,
  };
});

import { ArchiveForm } from './ArchiveForm';

const sourceSection = {
  title: 'Source',
  fields: [
    { name: 'source_db_id', label: 'Source Schema', type: 'schema', depends_on: 'service_id' },
    { name: 'source_db_name', label: 'Source Schema Name', type: 'string' },
    { name: 'source_table_id', label: 'Source Table', type: 'table', depends_on: 'source_db_id' },
    { name: 'source_table_name', label: 'Source Table Name', type: 'string' },
    { name: 'source_query', label: 'Source Query', type: 'string' },
  ],
} as unknown as FormSection;

function values() {
  return screen.getByTestId('values').textContent ?? '';
}

describe('ArchiveForm source mode toggle', () => {
  it('shows only the active mode fields and swaps them on toggle', async () => {
    const user = userEvent.setup();
    render(
      <ArchiveForm
        sections={[sourceSection]}
        onSubmit={vi.fn()}
        loading={false}
        defaultValues={{
          service_id: '',
          source_db_id: '',
          source_db_name: '',
          source_table_id: '',
          source_table_name: '',
          source_query: '',
        }}
      />,
    );

    // Schema mode: schema + table inputs, no query box.
    expect(screen.getByLabelText('Source Schema')).toBeInTheDocument();
    expect(screen.getByLabelText('Source Table')).toBeInTheDocument();
    expect(screen.queryByLabelText('Source Query')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Source Query' }));

    // Query mode: query box only, schema / table inputs gone.
    expect(screen.getByLabelText('Source Query')).toBeInTheDocument();
    expect(screen.queryByLabelText('Source Schema')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Source Table')).not.toBeInTheDocument();
  });

  it('clears schema/table values when switching to Source Query', async () => {
    const user = userEvent.setup();
    render(
      <ArchiveForm
        sections={[sourceSection]}
        onSubmit={vi.fn()}
        loading={false}
        defaultValues={{
          service_id: '',
          source_db_id: { id: 5, name: 'orders' },
          source_db_name: '',
          source_table_id: { id: 9, name: 'line_items' },
          source_table_name: '',
          source_query: '',
        }}
      />,
    );

    // Starts in schema mode with the seeded inventory schema.
    expect(values()).toContain('"source_db_id":{"id":5');

    await user.click(screen.getByRole('button', { name: 'Source Query' }));

    expect(values()).toContain('"source_db_id":""');
    expect(values()).toContain('"source_table_id":""');
    expect(values()).toContain('"source_db_name":""');
    expect(values()).toContain('"source_table_name":""');
  });

  it('clears the query when switching back to Schema + Table', async () => {
    const user = userEvent.setup();
    render(
      <ArchiveForm
        sections={[sourceSection]}
        onSubmit={vi.fn()}
        loading={false}
        defaultValues={{
          service_id: '',
          source_db_id: '',
          source_db_name: '',
          source_table_id: '',
          source_table_name: '',
          source_query: 'SELECT * FROM orders WHERE id < 100',
        }}
      />,
    );

    // source_query is truthy, so the form opens in query mode.
    expect(values()).toContain('"source_query":"SELECT');

    await user.click(screen.getByRole('button', { name: 'Schema + Table' }));

    expect(values()).toContain('"source_query":""');
  });

  it('submits only the active mode (query), never both branches', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ArchiveForm
        sections={[sourceSection]}
        onSubmit={onSubmit}
        loading={false}
        defaultValues={{
          service_id: '',
          source_db_id: { id: 5, name: 'orders' },
          source_db_name: '',
          source_table_id: { id: 9, name: 'line_items' },
          source_table_name: '',
          source_query: '',
        }}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Source Query' }));
    await user.type(screen.getByLabelText('Source Query'), 'SELECT 1');
    await user.click(screen.getByRole('button', { name: 'Submit' }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.source_query).toBe('SELECT 1');
    expect(payload.source_db_id).toBe('');
    expect(payload.source_table_id).toBe('');
  });
});
