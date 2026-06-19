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

import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';

import { server } from '../../../../tests/msw-server';
import NestedSettingGroup from '../NestedSettingGroup';
import { buildSettingTree, type GroupNode } from '../settingField';
import { makeSetting, makeWrapper } from './fixtures';

const SEP_BASE = 'http://localhost/api/sep/admin/settings/SEPSettings';

function nomadGroup(): GroupNode {
  const tree = buildSettingTree([
    makeSetting({
      key: 'NOMAD__ENDPOINT',
      key_path: ['NOMAD', 'ENDPOINT'],
      type: 'str',
      value: 'http://old:4646',
    }),
    makeSetting({
      key: 'NOMAD__TOKEN',
      key_path: ['NOMAD', 'TOKEN'],
      type: 'SecretStr',
      is_secret: true,
      value: '**********',
      has_override: true,
    }),
  ]);
  return tree[0] as GroupNode;
}

describe('NestedSettingGroup', () => {
  it('is collapsed by default and shows the parent segment + leaf count', () => {
    render(<NestedSettingGroup node={nomadGroup()} />, { wrapper: makeWrapper() });
    expect(screen.getByText('NOMAD')).toBeInTheDocument();
    // NOMAD__TOKEN is overridden in the fixture, so the summary reports both.
    expect(screen.getByText(/2 fields, 1 overridden/)).toBeInTheDocument();
    // The summary toggle starts collapsed.
    expect(screen.getByRole('button', { name: 'NOMAD nested settings' })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
  });

  it('reveals one editable row per nested leaf when expanded', async () => {
    const user = userEvent.setup();
    render(<NestedSettingGroup node={nomadGroup()} />, { wrapper: makeWrapper() });
    await user.click(screen.getByRole('button', { name: 'NOMAD nested settings' }));
    expect(screen.getByTestId('setting-row-NOMAD__ENDPOINT')).toBeInTheDocument();
    expect(screen.getByTestId('setting-row-NOMAD__TOKEN')).toBeInTheDocument();
  });

  it('saves an edited leaf via PATCH keyed by its __-delimited key', async () => {
    const body = vi.fn();
    server.use(
      http.patch(SEP_BASE, async ({ request }) => {
        body(await request.json());
        return HttpResponse.json([]);
      }),
    );
    const user = userEvent.setup();
    render(<NestedSettingGroup node={nomadGroup()} searchActive />, { wrapper: makeWrapper() });

    const input = screen.getByLabelText('NOMAD__ENDPOINT');
    await user.clear(input);
    await user.type(input, 'http://new:4646');
    const row = screen.getByTestId('setting-row-NOMAD__ENDPOINT');
    await user.click(within(row).getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(body).toHaveBeenCalledWith({ NOMAD__ENDPOINT: 'http://new:4646' }));
  });

  it('resets an overridden leaf via DELETE on its __-delimited key', async () => {
    const deleted = vi.fn();
    server.use(
      http.delete(`${SEP_BASE}/NOMAD__TOKEN`, () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const user = userEvent.setup();
    render(<NestedSettingGroup node={nomadGroup()} searchActive />, { wrapper: makeWrapper() });

    const row = screen.getByTestId('setting-row-NOMAD__TOKEN');
    await user.click(within(row).getByRole('button', { name: 'Reset to default' }));
    await waitFor(() => expect(deleted).toHaveBeenCalled());
  });

  it('surfaces a 422 inline next to the offending leaf', async () => {
    server.use(
      http.patch(SEP_BASE, () =>
        HttpResponse.json(
          { detail: [{ loc: ['body', 'NOMAD__ENDPOINT'], msg: 'Invalid endpoint URL' }] },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<NestedSettingGroup node={nomadGroup()} searchActive />, { wrapper: makeWrapper() });

    const input = screen.getByLabelText('NOMAD__ENDPOINT');
    await user.clear(input);
    await user.type(input, 'not-a-url');
    const row = screen.getByTestId('setting-row-NOMAD__ENDPOINT');
    await user.click(within(row).getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('Invalid endpoint URL')).toBeInTheDocument();
  });

  it('renders a nested sub-group for two-level nesting', async () => {
    const tree = buildSettingTree([
      makeSetting({
        key: 'SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE',
        key_path: ['SECURITY_HEADERS', 'STRICT_TRANSPORT_SECURITY', 'MAX_AGE'],
        type: 'int',
        value: 3600,
      }),
    ]);
    const user = userEvent.setup();
    render(<NestedSettingGroup node={tree[0] as GroupNode} />, { wrapper: makeWrapper() });

    await user.click(screen.getByRole('button', { name: 'SECURITY_HEADERS nested settings' }));
    // The inner submodel renders as its own expandable subgroup. The testid is
    // built from the segment chain joined on `.` (not `__`) so distinct chains
    // can never collide.
    const inner = screen.getByTestId(
      'nested-setting-group-SECURITY_HEADERS.STRICT_TRANSPORT_SECURITY',
    );
    expect(inner).toBeInTheDocument();
    await user.click(
      within(inner).getByRole('button', { name: 'STRICT_TRANSPORT_SECURITY nested settings' }),
    );
    expect(
      screen.getByTestId('setting-row-SECURITY_HEADERS__STRICT_TRANSPORT_SECURITY__MAX_AGE'),
    ).toBeInTheDocument();
  });

  it('auto-expands when a search is active', () => {
    render(<NestedSettingGroup node={nomadGroup()} searchActive />, { wrapper: makeWrapper() });
    expect(screen.getByRole('button', { name: 'NOMAD nested settings' })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});
