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
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router';
import type { ReactNode } from 'react';
import { ApiError, REDACTED_SECRET, useSettingsList, type SettingClassGroup } from '@sep/api';
import { ROUTES } from '@sep/shared';
import { DeliverySetupGate } from '../src/DeliverySetupGate';
import { Messages } from '../src/DeliverySetupGate.messages';

vi.mock('@sep/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@sep/api')>()),
  useSettingsList: vi.fn(),
}));

const settingsList = vi.mocked(useSettingsList);

const setting = (key: string, value: unknown, hasOverride = false) =>
  ({
    key,
    value,
    has_override: hasOverride,
    setting_class: 'SEPSettings',
    type: 'object',
  }) as unknown as SettingClassGroup['settings'][number];

/**
 * A LIST response whose `SEPSettings` group declares `declared` as the required
 * secret names and stores `storedSecrets` against them. Omitting `storedSecrets`
 * models a deployment that never supplied an override at all.
 */
const sepGroups = (
  declared: string[],
  storedSecrets?: Record<string, string>,
): SettingClassGroup[] =>
  [
    {
      setting_class: 'SEPSettings',
      is_app_owned: false,
      settings: [
        setting('DIAGNOSTICS_DELIVERY', {
          secrets: Object.fromEntries(declared.map((name) => [name, REDACTED_SECRET])),
        }),
        setting(
          'DIAGNOSTICS_DELIVERY_INPUTS',
          { endpoint: '', secrets: storedSecrets ?? {} },
          storedSecrets !== undefined,
        ),
      ],
    },
  ] as unknown as SettingClassGroup[];

const mockList = (overrides: Partial<ReturnType<typeof useSettingsList>> = {}) => {
  settingsList.mockReturnValue({
    data: undefined,
    isLoading: false,
    error: null,
    ...overrides,
  } as ReturnType<typeof useSettingsList>);
};

function renderWithProviders(ui: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const renderGate = (isAdmin = false) =>
  renderWithProviders(
    <DeliverySetupGate isAdmin={isAdmin}>
      <div data-testid="atw-app" />
    </DeliverySetupGate>,
  );

describe('DeliverySetupGate', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the app once delivery is configured', () => {
    mockList({ data: sepGroups(['sn_api_key'], { sn_api_key: 'secret' }) });
    renderGate();

    expect(screen.getByTestId('atw-app')).toBeInTheDocument();
    expect(screen.queryByTestId('atw-delivery-setup-prompt')).not.toBeInTheDocument();
  });

  it('prompts for setup when nothing is stored', () => {
    mockList({ data: sepGroups(['sn_api_key']) });
    renderGate();

    expect(screen.getByTestId('atw-delivery-setup-prompt')).toBeInTheDocument();
    expect(screen.getByText(Messages.title)).toBeInTheDocument();
    expect(screen.queryByTestId('atw-app')).not.toBeInTheDocument();
  });

  it('prompts for setup when a declared secret was stored empty', () => {
    mockList({ data: sepGroups(['sn_api_key'], { sn_api_key: '' }) });
    renderGate();

    expect(screen.getByTestId('atw-delivery-setup-prompt')).toBeInTheDocument();
  });

  it('renders the app when the plan declares no secrets and an override is stored', () => {
    // Nothing is left for the deployment to supply, so the override alone is as
    // configured as it can get — the endpoint would otherwise read as missing.
    mockList({ data: sepGroups([], {}) });
    renderGate();

    expect(screen.getByTestId('atw-app')).toBeInTheDocument();
  });

  it('prompts for setup when the stored values no longer match the plan', () => {
    mockList({ data: sepGroups(['sn_token'], { sn_api_key: 'secret' }) });
    renderGate();

    expect(screen.getByTestId('atw-delivery-setup-prompt')).toBeInTheDocument();
  });

  it('renders the app when the settings carry no delivery inputs key', () => {
    // Nothing for an admin to fill in, so the prompt would name a remedy
    // nobody in this deployment can carry out.
    mockList({
      data: [
        {
          setting_class: 'SEPSettings',
          is_app_owned: false,
          settings: [setting('DIAGNOSTICS_DELIVERY', { secrets: {} })],
        },
      ] as unknown as SettingClassGroup[],
    });
    renderGate(true);

    expect(screen.getByTestId('atw-app')).toBeInTheDocument();
    expect(screen.queryByTestId('atw-delivery-setup-prompt')).not.toBeInTheDocument();
  });

  it('renders the app when the settings read failed', () => {
    mockList({ error: new ApiError({ kind: 'network', message: 'down' }) });
    renderGate();

    expect(screen.getByTestId('atw-app')).toBeInTheDocument();
  });

  it('renders the app when the admin-only settings read was forbidden', () => {
    mockList({
      error: new ApiError({ kind: 'http', status: 403, message: 'Forbidden' }),
    });
    renderGate();

    expect(screen.getByTestId('atw-app')).toBeInTheDocument();
    expect(screen.queryByTestId('atw-delivery-setup-prompt')).not.toBeInTheDocument();
  });

  it('waits while the settings are loading', () => {
    mockList({ isLoading: true });
    renderGate();

    expect(screen.getByLabelText(Messages.loading)).toBeInTheDocument();
    expect(screen.queryByTestId('atw-app')).not.toBeInTheDocument();
  });

  it('tells a non-admin to ask an administrator, with no call to action', () => {
    mockList({ data: sepGroups(['sn_api_key']) });
    renderGate(false);

    expect(screen.getByText(Messages.notConfigured)).toBeInTheDocument();
    expect(screen.queryByTestId('atw-delivery-setup-cta')).not.toBeInTheDocument();
    expect(screen.queryByText(Messages.adminInstructions)).not.toBeInTheDocument();
  });

  it('points an admin at the settings page and names the key to fill in', () => {
    mockList({ data: sepGroups(['sn_api_key']) });
    renderGate(true);

    expect(screen.getByText(Messages.notConfigured)).toBeInTheDocument();
    expect(screen.getByText(Messages.adminInstructions)).toBeInTheDocument();
    expect(screen.getByTestId('atw-delivery-setup-cta')).toHaveAttribute('href', ROUTES.settings);
  });
});
