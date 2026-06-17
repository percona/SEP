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
import { describe, expect, it } from 'vitest';
import { FormProvider, useForm } from 'react-hook-form';
import { ArchiveSchemaCombo, type ArchiveComboOption } from './ArchiveSchemaCombo';

const OPTIONS: ArchiveComboOption[] = [
  { id: 10, name: 'app_prod' },
  { id: 11, name: 'analytics' },
];

function Harness() {
  const methods = useForm({ defaultValues: { source_db_id: '', source_db_name: '' } });
  const idValue = methods.watch('source_db_id');
  const nameValue = methods.watch('source_db_name');
  return (
    <FormProvider {...methods}>
      <ArchiveSchemaCombo
        idFieldName="source_db_id"
        nameFieldName="source_db_name"
        label="Source Schema"
        options={OPTIONS}
      />
      <output data-testid="values">{JSON.stringify({ id: idValue, name: nameValue })}</output>
    </FormProvider>
  );
}

function readValues() {
  return JSON.parse(screen.getByTestId('values').textContent ?? '{}') as {
    id: unknown;
    name: unknown;
  };
}

describe('ArchiveSchemaCombo', () => {
  it('emits the inventory option (id) when a listed value is picked', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByLabelText('Source Schema'));
    await user.click(await screen.findByText('app_prod'));

    const values = readValues();
    // The option object is written to the id field; the payload layer unwraps it
    // to the scalar source_db_id on submit. The name field stays empty.
    expect(values.id).toEqual({ id: 10, name: 'app_prod' });
    expect(values.name).toBe('');
  });

  it('emits the typed name when a new (non-inventory) value is entered', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.type(screen.getByLabelText('Source Schema'), 'brand_new_db');

    const values = readValues();
    expect(values.name).toBe('brand_new_db');
    expect(values.id).toBe('');
  });

  it('clears both wire fields when the value is cleared', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByLabelText('Source Schema'));
    await user.click(await screen.findByText('analytics'));
    expect(readValues().id).toEqual({ id: 11, name: 'analytics' });

    await user.clear(screen.getByLabelText('Source Schema'));

    const values = readValues();
    expect(values.id).toBe('');
    expect(values.name).toBe('');
  });
});
