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
import { FormProvider, useForm, useFormContext } from 'react-hook-form';

// Both destination blocks communicate only through react-hook-form context: the
// relocated schema combo lives in ArchiveDestinationFields, while the service
// that supplies its inventory options is controlled in ArchiveDestinationHostFields.
// This mock keeps the schema/table inventory and a write-through ServiceSelector so
// the cross-component cascade can be exercised end-to-end.
vi.mock('@sep/framework', () => ({
  useSchemas: ({ enabled }: { enabled?: boolean }) => ({
    data: enabled ? [{ id: 5, name: 'orders' }] : [],
    isLoading: false,
  }),
  useTables: ({ enabled }: { enabled?: boolean }) => ({
    data: enabled ? [{ id: 9, name: 'line_items' }] : [],
    isLoading: false,
  }),
  SchemaFormRenderer: () => null,
  ServiceSelector: ({ name, label }: { name: string; label: string }) => {
    const { setValue } = useFormContext();
    return (
      <button type="button" onClick={() => setValue(name, { id: 7, name: 'destsvc' })}>
        {label}
      </button>
    );
  },
}));

import { ArchiveDestinationFields, ArchiveDestinationHostFields } from './ArchiveForm';

type Defaults = Record<string, unknown>;

function Harness({
  defaults,
  initialHostMode = 'service',
}: {
  defaults: Defaults;
  initialHostMode?: 'service' | 'manual';
}) {
  const methods = useForm({ defaultValues: defaults });
  const [destMode, setDestMode] = useState<'table' | 'file'>('table');
  const [useDifferentHost, setUseDifferentHost] = useState(true);
  const [hostMode, setHostMode] = useState<'service' | 'manual'>(initialHostMode);
  return (
    <FormProvider {...methods}>
      <ArchiveDestinationFields mode={destMode} onModeChange={setDestMode} />
      <ArchiveDestinationHostFields
        useDifferentHost={useDifferentHost}
        onUseDifferentHostChange={setUseDifferentHost}
        hostMode={hostMode}
        onHostModeChange={setHostMode}
        serviceTypes={['mysql']}
      />
      <output data-testid="values">{JSON.stringify(methods.watch())}</output>
    </FormProvider>
  );
}

function values() {
  return screen.getByTestId('values').textContent ?? '';
}

const SEEDED: Defaults = {
  dest_service_id: { id: 7, name: 'destsvc' },
  dest_host: '',
  dest_port: '',
  dest_db_id: { id: 5, name: 'orders' },
  dest_db_name: '',
  dest_table_id: 9,
  dest_table_name: '',
  dest_file: '',
};

describe('Destination section ↔ Destination Host cascade', () => {
  it('clears the relocated schema and table when the host switches to manual (3c)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} initialHostMode="service" />);

    expect(values()).toContain('"dest_db_id":{"id":5');
    expect(values()).toContain('"dest_table_id":9');

    // Switching to manual host clears dest_service_id in the host block; the
    // Destination section's service cascade must then drop the inventory schema
    // (it can no longer resolve without a service) and its table.
    await user.click(screen.getByRole('button', { name: 'Enter host manually' }));

    expect(values()).toContain('"dest_service_id":""');
    expect(values()).toContain('"dest_db_id":""');
    expect(values()).toContain('"dest_table_id":""');
  });

  it('clears the relocated schema and table when "Use a different host?" is turned off', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={SEEDED} initialHostMode="service" />);

    await user.click(screen.getByLabelText('Use a different host?'));

    expect(values()).toContain('"dest_service_id":""');
    expect(values()).toContain('"dest_db_id":""');
    expect(values()).toContain('"dest_table_id":""');
  });
});
