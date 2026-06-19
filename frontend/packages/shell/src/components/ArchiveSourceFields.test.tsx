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
import { FormProvider, useForm } from 'react-hook-form';

// Stub the framework inventory hooks with fixed options so the raw-id → name
// resolution path can be exercised.
vi.mock('@sep/framework', () => ({
  useSchemas: () => ({
    data: [
      { id: 5, name: 'orders' },
      { id: 99, name: 'other_schema' },
    ],
    isLoading: false,
  }),
  useTables: () => ({ data: [{ id: 9, name: 'line_items' }], isLoading: false }),
}));

import { ArchiveSourceFields } from './ArchiveForm';

type Defaults = Record<string, unknown>;

function Harness({ defaults }: { defaults: Defaults }) {
  const methods = useForm({ defaultValues: defaults });
  return (
    <FormProvider {...methods}>
      <button type="button" onClick={() => methods.setValue('service_id', { id: 2, name: 'svc2' })}>
        change-service
      </button>
      <button
        type="button"
        onClick={() => methods.setValue('source_db_id', { id: 99, name: 'other_schema' })}
      >
        change-schema
      </button>
      <ArchiveSourceFields mode="schema" onModeChange={() => {}} />
      <output data-testid="values">{JSON.stringify(methods.watch())}</output>
    </FormProvider>
  );
}

function values() {
  return screen.getByTestId('values').textContent ?? '';
}

const SEEDED: Defaults = {
  service_id: { id: 1, name: 'svc1' },
  source_db_id: { id: 5, name: 'orders' },
  source_db_name: '',
  source_table_id: { id: 9, name: 'line_items' },
  source_table_name: '',
  source_query: '',
};

describe('ArchiveSourceFields cascades', () => {
  it('does not clear seeded values on mount (edit prefill)', () => {
    render(<Harness defaults={SEEDED} />);
    expect(values()).toContain('"source_db_id":{"id":5');
    expect(values()).toContain('"source_table_id":{"id":9');
  });

  it('clears schema and table when the source service changes', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    await user.click(screen.getByRole('button', { name: 'change-service' }));

    expect(values()).toContain('"source_db_id":""');
    expect(values()).toContain('"source_db_name":""');
    expect(values()).toContain('"source_table_id":""');
    expect(values()).toContain('"source_table_name":""');
  });

  it('clears the table when a different inventory schema is picked', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    await user.click(screen.getByRole('button', { name: 'change-schema' }));

    expect(values()).toContain('"source_db_id":{"id":99');
    expect(values()).toContain('"source_table_id":""');
    expect(values()).toContain('"source_table_name":""');
  });

  it('downgrades a picked schema to a name when a custom table is typed (5a invariant)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} />);

    // Type a custom table while the schema is an inventory pick. The normaliser
    // must convert the schema side to a name so the wire payload is both-names,
    // never a mixed id + name that validator 5a rejects.
    const tableInput = screen.getByLabelText('Source Table');
    await user.clear(tableInput);
    await user.type(tableInput, 'new_table');

    const v = values();
    expect(v).toContain('"source_table_name":"new_table"');
    expect(v).toContain('"source_table_id":""');
    expect(v).toContain('"source_db_name":"orders"');
    expect(v).toContain('"source_db_id":""');
  });

  it('resolves a raw numeric schema id to its real name (not the id) on downgrade', async () => {
    const user = userEvent.setup();
    // Edit prefill stores raw numeric ids, not option objects.
    render(
      <Harness
        defaults={{
          service_id: { id: 1, name: 'svc1' },
          source_db_id: 5,
          source_db_name: '',
          source_table_id: 9,
          source_table_name: '',
          source_query: '',
        }}
      />,
    );

    const tableInput = screen.getByLabelText('Source Table');
    await user.clear(tableInput);
    await user.type(tableInput, 'new_table');

    const v = values();
    // The schema id 5 downgrades to its inventory name 'orders', never "5".
    expect(v).toContain('"source_db_name":"orders"');
    expect(v).not.toContain('"source_db_name":"5"');
    expect(v).toContain('"source_db_id":""');
  });
});
