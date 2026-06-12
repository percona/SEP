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

import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FormProvider, useForm } from 'react-hook-form';
import { MultiChoiceField } from './MultiChoiceField';
import type { MultiChoiceField as MultiChoiceFieldType, ChoiceOption } from '../types';

function Harness({ field }: { field: MultiChoiceFieldType }) {
  const methods = useForm({ defaultValues: { [field.name]: [] as string[] } });
  return (
    <FormProvider {...methods}>
      <MultiChoiceField field={field} />
    </FormProvider>
  );
}

const CHOICES: ChoiceOption[] = [
  { value: 'a', label: 'Alpha' },
  {
    value: 'b',
    label: 'Beta',
    disabled: true,
    disabled_reason: 'Beta is retired.',
  },
];

describe('MultiChoiceField', () => {
  it('disables the matching option and shows its reason on hover', async () => {
    const user = userEvent.setup();
    const field: MultiChoiceFieldType = {
      type: 'multi_choice',
      name: 'flags',
      label: 'Flags',
      choices: CHOICES,
    };
    render(<Harness field={field} />);

    await user.click(screen.getByRole('combobox'));

    const betaLabel = await screen.findByText('Beta');
    expect(betaLabel.closest('[role="option"]')).toHaveAttribute('aria-disabled', 'true');

    await user.hover(betaLabel);
    await waitFor(() => {
      expect(screen.getByRole('tooltip')).toHaveTextContent('Beta is retired.');
    });
  });
});
