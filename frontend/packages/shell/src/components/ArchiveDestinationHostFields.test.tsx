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

// ServiceSelector is stubbed with a write-through input so the inventory branch
// can be asserted without the real react-query-backed component. The other
// barrel members are inert (imported only because ArchiveForm pulls the barrel).
vi.mock('@sep/framework', () => ({
  useSchemas: () => ({ data: [], isLoading: false }),
  useTables: () => ({ data: [], isLoading: false }),
  SchemaFormRenderer: () => null,
  ServiceSelector: ({ name, label }: { name: string; label: string }) => {
    const { setValue } = useFormContext();
    return (
      <button type="button" onClick={() => setValue(name, { id: 4, name: 'destsvc' })}>
        {label}
      </button>
    );
  },
}));

import { ArchiveDestinationHostFields } from './ArchiveForm';

type Defaults = Record<string, unknown>;

function Harness({
  defaults,
  initialUseDifferentHost = false,
  initialHostMode = 'service',
}: {
  defaults: Defaults;
  initialUseDifferentHost?: boolean;
  initialHostMode?: 'service' | 'manual';
}) {
  const methods = useForm({ defaultValues: defaults });
  const [useDifferentHost, setUseDifferentHost] = useState(initialUseDifferentHost);
  const [hostMode, setHostMode] = useState<'service' | 'manual'>(initialHostMode);
  return (
    <FormProvider {...methods}>
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

const EMPTY: Defaults = {
  dest_service_id: '',
  dest_host: '',
  dest_port: '',
};

describe('ArchiveDestinationHostFields', () => {
  it('hides every host field until "Use a different host?" is checked', () => {
    render(<Harness defaults={EMPTY} />);
    expect(screen.getByLabelText('Use a different host?')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Pick from inventory' })).not.toBeInTheDocument();
    // The mocked ServiceSelector renders a <button>, so match it by role to
    // avoid a query that can never find it (a false-negative absence assertion).
    expect(screen.queryByRole('button', { name: 'Destination Service' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Destination Host')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Destination Port')).not.toBeInTheDocument();
  });

  it('reveals the inventory service picker by default when checked', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={EMPTY} />);

    await user.click(screen.getByLabelText('Use a different host?'));

    expect(screen.getByRole('button', { name: 'Pick from inventory' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Destination Service' })).toBeInTheDocument();
    // Manual host fields stay hidden in the inventory branch.
    expect(screen.queryByLabelText('Destination Host')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Destination Port')).not.toBeInTheDocument();
  });

  it('renders Destination Port ONLY in the manual-host branch', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={EMPTY} initialUseDifferentHost initialHostMode="service" />);

    // Inventory branch: no port.
    expect(screen.queryByLabelText('Destination Port')).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Enter host manually' }));

    // Manual branch: host + port appear, the inventory picker is gone.
    expect(screen.getByLabelText('Destination Host')).toBeInTheDocument();
    expect(screen.getByLabelText('Destination Port')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Destination Service' })).not.toBeInTheDocument();
  });

  it('clears manual host/port when switching to the inventory branch', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={EMPTY} initialUseDifferentHost initialHostMode="manual" />);

    await user.type(screen.getByLabelText('Destination Host'), 'db2.example.com');
    await user.type(screen.getByLabelText('Destination Port'), '3307');
    expect(values()).toContain('"dest_host":"db2.example.com"');

    await user.click(screen.getByRole('button', { name: 'Pick from inventory' }));

    expect(values()).toContain('"dest_host":""');
    expect(values()).toContain('"dest_port":""');
  });

  it('clears the inventory service when switching to the manual branch (3c)', async () => {
    const user = userEvent.setup();
    render(<Harness defaults={EMPTY} initialUseDifferentHost initialHostMode="service" />);

    await user.click(screen.getByRole('button', { name: 'Destination Service' }));
    expect(values()).toContain('"dest_service_id":{"id":4');

    await user.click(screen.getByRole('button', { name: 'Enter host manually' }));

    expect(values()).toContain('"dest_service_id":""');
  });

  it('drops all host fields when "Use a different host?" is unchecked', async () => {
    const user = userEvent.setup();
    render(
      <Harness
        defaults={{ dest_service_id: { id: 4, name: 'destsvc' }, dest_host: '', dest_port: '' }}
        initialUseDifferentHost
        initialHostMode="service"
      />,
    );

    expect(values()).toContain('"dest_service_id":{"id":4');

    await user.click(screen.getByLabelText('Use a different host?'));

    expect(values()).toContain('"dest_service_id":""');
    expect(values()).toContain('"dest_host":""');
    expect(values()).toContain('"dest_port":""');
    // The opt-in is off, so the branch UI is gone.
    expect(screen.queryByRole('button', { name: 'Pick from inventory' })).not.toBeInTheDocument();
  });
});
