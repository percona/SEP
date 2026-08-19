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

import SettingEditField from '../SettingEditField';
import { makeSetting } from './fixtures';

describe('SettingEditField dispatch', () => {
  it('renders a toggle for booleans and reports changes', async () => {
    const onChange = vi.fn();
    render(
      <SettingEditField
        setting={makeSetting({ key: 'FLAG', type: 'bool', value: false })}
        value={false}
        onChange={onChange}
      />,
    );
    const toggle = screen.getByRole('switch');
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('renders a select with literal options', async () => {
    const onChange = vi.fn();
    render(
      <SettingEditField
        setting={makeSetting({ key: 'MODE', type: "Literal['warn', 'fail']" })}
        value="warn"
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText('MODE'));
    await userEvent.click(await screen.findByRole('option', { name: 'fail' }));
    expect(onChange).toHaveBeenCalledWith('fail');
  });

  it('renders API option labels for enum settings', async () => {
    const onChange = vi.fn();
    render(
      <SettingEditField
        setting={makeSetting({
          key: 'LOGGING',
          type: 'LogLevel',
          value: 30,
          options: [
            { label: 'WARNING', value: 30 },
            { label: 'DEBUG', value: 10 },
          ],
        })}
        value="30"
        onChange={onChange}
      />,
    );
    await userEvent.click(screen.getByLabelText('LOGGING'));
    expect(await screen.findByRole('option', { name: 'WARNING' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'DEBUG' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'DEBUG' }));
    expect(onChange).toHaveBeenCalledWith('10');
  });

  it('renders a number input for integers', () => {
    render(
      <SettingEditField
        setting={makeSetting({ key: 'COUNT', type: 'int' })}
        value="5"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByLabelText('COUNT')).toHaveAttribute('type', 'number');
  });

  it('renders a masked secret input that does not echo the redacted value', () => {
    render(
      <SettingEditField
        setting={makeSetting({
          key: 'TOKEN',
          type: 'SecretStr',
          is_secret: true,
          value: '**********',
        })}
        value=""
        onChange={vi.fn()}
      />,
    );
    const input = screen.getByLabelText('TOKEN');
    expect(input).toHaveAttribute('type', 'password');
    expect(input).toHaveValue('');
  });

  it('renders a read-only note for complex fields', () => {
    render(
      <SettingEditField
        setting={makeSetting({
          key: 'NESTED',
          type: 'SubModel',
          is_complex: true,
          value: { a: 1 },
        })}
        value=""
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText('nested editing not yet supported')).toBeInTheDocument();
  });

  it('renders inline error text', () => {
    render(
      <SettingEditField
        setting={makeSetting({ key: 'NAME', type: 'str' })}
        value="x"
        onChange={vi.fn()}
        error="Something is wrong"
      />,
    );
    expect(screen.getByText('Something is wrong')).toBeInTheDocument();
  });
});
