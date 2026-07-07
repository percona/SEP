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
import { FreeSoloMultiSelect } from './FreeSoloMultiSelect';
import type { MultiReferenceOption } from './freeSoloMultiValue';

const OPTIONS: MultiReferenceOption[] = [
  { id: 10, name: 'app_prod' },
  { id: 11, name: 'analytics' },
];

const labelOf = (o: MultiReferenceOption) => o.name;

function Harness({
  defaultValue = [],
  allowCustom = true,
  options = OPTIONS,
}: {
  defaultValue?: unknown;
  allowCustom?: boolean;
  options?: readonly MultiReferenceOption[];
}) {
  const methods = useForm({ defaultValues: { services: defaultValue } });
  return (
    <FormProvider {...methods}>
      <FreeSoloMultiSelect<MultiReferenceOption>
        name="services"
        label="Services"
        options={options}
        getOptionLabel={labelOf}
        allowCustom={allowCustom}
      />
      <output data-testid="value">{JSON.stringify(methods.watch('services'))}</output>
    </FormProvider>
  );
}

const value = () => screen.getByTestId('value').textContent;

describe('FreeSoloMultiSelect', () => {
  it('commits inventory ids when options are picked', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText('Services'));
    await user.click(await screen.findByText('app_prod'));
    await user.click(screen.getByLabelText('Services'));
    await user.click(await screen.findByText('analytics'));
    expect(value()).toBe('[10,11]');
  });

  it('commits a string when a novel value is typed', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText('Services'), 'custom_svc{Enter}');
    expect(value()).toBe('["custom_svc"]');
  });

  it('commits a mixed [id, string] array', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByLabelText('Services'));
    await user.click(await screen.findByText('app_prod'));
    await user.type(screen.getByLabelText('Services'), 'custom_svc{Enter}');
    expect(value()).toBe('[10,"custom_svc"]');
  });

  it('resolves a typed value matching an option label to its id', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByLabelText('Services'), 'analytics{Enter}');
    expect(value()).toBe('[11]');
  });

  it('yields an empty array when cleared', async () => {
    const user = userEvent.setup();
    render(<Harness defaultValue={[10, 11]} />);
    await user.click(screen.getByLabelText('Clear'));
    expect(value()).toBe('[]');
  });

  it('renders inventory picks and free-typed values as chips (free-typed italic)', async () => {
    const user = userEvent.setup();
    render(<Harness defaultValue={[10]} />);
    // Inventory chip renders its label as plain text.
    expect(screen.getByText('app_prod')).toBeInTheDocument();
    // A free-typed value renders its chip label in italics (an <em>).
    await user.type(screen.getByLabelText('Services'), 'custom_svc{Enter}');
    const chip = await screen.findByText('custom_svc');
    expect(chip.tagName).toBe('EM');
  });

  it('closed mode (allowCustom=false) offers no create suggestion and drops typed text', async () => {
    const user = userEvent.setup();
    render(<Harness allowCustom={false} />);
    await user.type(screen.getByLabelText('Services'), 'not_an_option');
    // No "create" suggestion is offered for the typed text.
    expect(screen.queryByText('not_an_option')).not.toBeInTheDocument();
    // Pressing Enter does not commit the typed text in closed mode.
    await user.keyboard('{Enter}');
    expect(value()).toBe('[]');
  });

  it('closed mode still commits inventory picks', async () => {
    const user = userEvent.setup();
    render(<Harness allowCustom={false} />);
    await user.click(screen.getByLabelText('Services'));
    await user.click(await screen.findByText('analytics'));
    expect(value()).toBe('[11]');
  });

  it('round-trips a stored [id, custom] array through the display', () => {
    render(<Harness defaultValue={[11, 'legacy_svc']} />);
    // The stored id resolves to its option label; the free string is kept.
    expect(screen.getByText('analytics')).toBeInTheDocument();
    expect(screen.getByText('legacy_svc')).toBeInTheDocument();
    expect(value()).toBe('[11,"legacy_svc"]');
  });
});
