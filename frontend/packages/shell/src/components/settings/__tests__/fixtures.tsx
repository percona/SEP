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

import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { SettingClassGroup, SettingResponse } from '@sep/api';

import { NotificationProvider } from '../../../contexts/notification';

/** Build a SettingResponse with sensible defaults overridable per field. */
export function makeSetting(overrides: Partial<SettingResponse> = {}): SettingResponse {
  return {
    setting_class: 'SEPSettings',
    key: 'SOME_KEY',
    value: 'value',
    default_value: 'value',
    type: 'str',
    reload: 'hot',
    description: 'A description',
    is_secret: false,
    is_complex: false,
    has_override: false,
    is_advanced: false,
    is_applicable: true,
    ...overrides,
  };
}

/** The SEP-endpoint list payload used across tests. */
export const sepListResponse = {
  groups: [
    {
      setting_class: 'SEPSettings',
      is_app_owned: false,
      settings: [
        makeSetting({ key: 'SYNC_REFRESH_TIME', value: 5, default_value: 5, type: 'int' }),
        makeSetting({
          key: 'CONNECTIVITY_CHECK_DEFAULT',
          value: true,
          default_value: true,
          type: 'bool',
        }),
        makeSetting({
          key: 'STATIC_DIR',
          value: '/srv/static',
          type: 'str',
          reload: 'not_overridable',
        }),
        makeSetting({
          key: 'API_SECRET',
          value: '**********',
          type: 'SecretStr',
          is_secret: true,
        }),
        makeSetting({
          key: 'FOOTER_TEMPLATE',
          value: '<footer/>',
          default_value: '<footer/>',
          type: 'str',
          reload: 'hot',
          is_advanced: true,
        }),
      ],
    },
    {
      setting_class: 'SnippetsSettings',
      is_app_owned: false,
      settings: [
        makeSetting({
          setting_class: 'SnippetsSettings',
          key: 'ENABLE_MANUAL_SYNC',
          value: false,
          default_value: false,
          type: 'bool',
        }),
      ],
    },
  ],
};

/** The Tasks-endpoint list payload used across tests. */
export const tasksListResponse = {
  groups: [
    {
      setting_class: 'TasksSettings',
      is_app_owned: false,
      settings: [
        makeSetting({
          setting_class: 'TasksSettings',
          key: 'STALENESS_THRESHOLD_SECONDS',
          value: 3600,
          default_value: 3600,
          type: 'int',
          has_override: true,
        }),
        makeSetting({
          setting_class: 'TasksSettings',
          key: 'PRE_EXECUTION_CONNECTIVITY_CHECK',
          value: 'warn',
          default_value: 'warn',
          type: "Literal['warn', 'fail', 'skip']",
        }),
      ],
    },
  ],
} satisfies { groups: SettingClassGroup[] };

/** Wrap children with the providers the settings tree depends on. */
export function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <NotificationProvider>{children}</NotificationProvider>
      </QueryClientProvider>
    );
  };
}
