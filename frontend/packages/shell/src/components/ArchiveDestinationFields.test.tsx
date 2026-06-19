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
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FormProvider, useForm } from 'react-hook-form';

// Stub the framework barrel: fixed inventory options for the schema/table combos
// plus inert SchemaFormRenderer / ServiceSelector so importing ArchiveForm (which
// pulls the whole barrel at module load) does not drag in the real dependencies.
vi.mock('@sep/framework', () => ({
  useSchemas: ({ enabled }: { enabled?: boolean }) => ({
    data: enabled
      ? [
          { id: 5, name: 'orders' },
          { id: 99, name: 'other_schema' },
        ]
      : [],
    isLoading: false,
  }),
  useTables: ({ enabled }: { enabled?: boolean }) => ({
    data: enabled ? [{ id: 9, name: 'line_items' }] : [],
    isLoading: false,
  }),
  SchemaFormRenderer: () => null,
  ServiceSelector: () => null,
}));

import { ArchiveDestinationFields } from './ArchiveForm';

type Defaults = Record<string, unknown>;

function Harness({
  defaults,
  initialMode = 'table',
}: {
  defaults: Defaults;
  initialMode?: 'table' | 'file';
}) {
  const methods = useForm({ defaultValues: defaults });
  const [mode, setMode] = useState<'table' | 'file'>(initialMode);
  return (
    <FormProvider {...methods}>
      <button
        type="button"
        onClick={() => methods.setValue('dest_service_id', { id: 7, name: 'destsvc' })}
      >
        change-service
      </button>
      <button
        type="button"
        onClick={() => methods.setValue('dest_db_id', { id: 99, name: 'other_schema' })}
      >
        change-schema
      </button>
      <ArchiveDestinationFields mode={mode} onModeChange={setMode} />
      <output data-testid="values">{JSON.stringify(methods.watch())}</output>
    </FormProvider>
  );
}

function values() {
  return screen.getByTestId('values').textContent ?? '';
}

const SEEDED: Defaults = {
  dest_service_id: { id: 7, name: 'destsvc' },
  dest_db_id: { id: 5, name: 'orders' },
  dest_db_name: '',
  dest_table_id: 9,
  dest_table_name: '',
  dest_file: '',
};

describe('ArchiveDestinationFields', () => {
  it('does not clear seeded values on mount (edit prefill)', () => {
    render(<Harness defaults={SEEDED} />);
    expect(values()).toContain('"dest_db_id":{"id":5');
    expect(values()).toContain('"dest_table_id":9');
  });

  it('shows the schema and table combos in table mode, not the file input', () => {
    render(<Harness defaults={SEEDED} />);
    expect(screen.getByLabelText('Destination Schema')).toBeInTheDocument();
    expect(screen.getByLabelText('Destination Table')).toBeInTheDocument();
    expect(screen.queryByLabelText('Destination File')).not.toBeInTheDocument();
  });

  it('shows only the file input in file mode and swaps on toggle', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    await user.click(screen.getByRole('button', { name: 'Destination File' }));

    expect(screen.getByLabelText('Destination File')).toBeInTheDocument();
    expect(screen.queryByLabelText('Destination Schema')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Destination Table')).not.toBeInTheDocument();
  });

  it('clears schema/table when switching to Destination File', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    expect(values()).toContain('"dest_db_id":{"id":5');

    await user.click(screen.getByRole('button', { name: 'Destination File' }));

    expect(values()).toContain('"dest_db_id":""');
    expect(values()).toContain('"dest_table_id":""');
    expect(values()).toContain('"dest_db_name":""');
    expect(values()).toContain('"dest_table_name":""');
  });

  it('clears the file path when switching back to Schema + Table', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={{ ...SEEDED, dest_file: '/tmp/archive.csv' }} initialMode="file" />);

    expect(values()).toContain('"dest_file":"/tmp/archive.csv"');

    await user.click(screen.getByRole('button', { name: 'Schema + Table' }));

    expect(values()).toContain('"dest_file":""');
  });

  it('clears schema and table when the destination service changes', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={{ ...SEEDED, dest_service_id: { id: 1, name: 'svc1' } }} />);

    await user.click(screen.getByRole('button', { name: 'change-service' }));

    expect(values()).toContain('"dest_db_id":""');
    expect(values()).toContain('"dest_db_name":""');
    expect(values()).toContain('"dest_table_id":""');
    expect(values()).toContain('"dest_table_name":""');
  });

  it('clears the table when a different inventory schema is picked', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    await user.click(screen.getByRole('button', { name: 'change-schema' }));

    expect(values()).toContain('"dest_db_id":{"id":99');
    expect(values()).toContain('"dest_table_id":""');
    expect(values()).toContain('"dest_table_name":""');
  });

  it('clears a picked table when the inventory schema is typed over (no stale id)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    // Start with an inventory schema + table, then type a custom schema name so
    // dest_db_id resolves to null. The dependent table must clear, otherwise a
    // stale dest_table_id would be submitted against a schema it no longer matches.
    const schemaInput = screen.getByLabelText('Destination Schema');
    await user.clear(schemaInput);
    await user.type(schemaInput, 'custom_schema');

    const v = values();
    expect(v).toContain('"dest_db_name":"custom_schema"');
    expect(v).toContain('"dest_db_id":""');
    expect(v).toContain('"dest_table_id":""');
    expect(v).toContain('"dest_table_name":""');
  });

  it('emits a typed Destination Table as a name and clears the id', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    const tableInput = screen.getByLabelText('Destination Table');
    await user.clear(tableInput);
    await user.type(tableInput, 'archived_rows');

    const v = values();
    expect(v).toContain('"dest_table_name":"archived_rows"');
    expect(v).toContain('"dest_table_id":""');
  });

  it('emits a picked Destination Table as a scalar inventory id (not an object)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={{ ...SEEDED, dest_table_id: '', dest_table_name: '' }} />);

    const tableInput = screen.getByLabelText('Destination Table');
    await user.click(tableInput);
    await user.type(tableInput, 'line');
    await user.click(await screen.findByText('line_items'));

    const v = values();
    // IntegerField does not unwrap option objects on submit, so the combo must
    // write the scalar id directly.
    expect(v).toContain('"dest_table_id":9');
    expect(v).not.toContain('"dest_table_id":{');
    expect(v).toContain('"dest_table_name":""');
  });

  it('emits a picked Destination Schema as an option object (unwrapped on submit)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={{ ...SEEDED, dest_db_id: '', dest_db_name: '' }} />);

    const schemaInput = screen.getByLabelText('Destination Schema');
    await user.click(schemaInput);
    await user.type(schemaInput, 'order');
    await user.click(await screen.findByText('orders'));

    const v = values();
    // SchemaField unwraps the option to its scalar id on submit, so the combo
    // keeps the full object in form state for display.
    expect(v).toContain('"dest_db_id":{"id":5');
    expect(v).toContain('"dest_db_name":""');
  });
});
