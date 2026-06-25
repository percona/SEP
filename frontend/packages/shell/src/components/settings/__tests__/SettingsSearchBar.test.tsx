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

import SettingsSearchBar from '../SettingsSearchBar';
import { DEFAULT_SETTINGS_FILTERS } from '../filters';

describe('SettingsSearchBar', () => {
  it('renders the Advanced control hidden by default', () => {
    render(
      <SettingsSearchBar
        filters={DEFAULT_SETTINGS_FILTERS}
        onChange={vi.fn()}
        settingClasses={['SEPSettings']}
      />,
    );
    // The select shows its current value's label; default is hidden.
    expect(screen.getByLabelText('Filter by advanced')).toHaveTextContent('Hidden');
  });

  it('reports advanced: shown when the admin reveals advanced settings', async () => {
    const onChange = vi.fn();
    render(
      <SettingsSearchBar
        filters={DEFAULT_SETTINGS_FILTERS}
        onChange={onChange}
        settingClasses={['SEPSettings']}
      />,
    );

    await userEvent.click(screen.getByLabelText('Filter by advanced'));
    await userEvent.click(await screen.findByRole('option', { name: 'Shown' }));

    expect(onChange).toHaveBeenCalledWith({ ...DEFAULT_SETTINGS_FILTERS, advanced: 'shown' });
  });
});
