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

import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import {
  settingErrorMessage,
  usePatchSetting,
  useResetSetting,
  useSettingsList,
  type ApiError,
} from '@sep/api';

import { server } from '../../../../tests/msw-server';
import { makeWrapper, sepListResponse, tasksListResponse } from './fixtures';

const SEP_URL = 'http://localhost/api/sep/admin/settings/';
const TASKS_URL = 'http://localhost/api/tasks/admin/settings/';

describe('useSettingsList', () => {
  it('fans out to both endpoints and merges groups by class', async () => {
    server.use(
      http.get(SEP_URL, () => HttpResponse.json(sepListResponse)),
      http.get(TASKS_URL, () => HttpResponse.json(tasksListResponse)),
    );

    const { result } = renderHook(() => useSettingsList(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const classes = result.current.data?.map((g) => g.setting_class);
    expect(classes).toEqual(['SEPSettings', 'SnippetsSettings', 'TasksSettings']);
  });
});

describe('usePatchSetting', () => {
  it('PATCHes the owning endpoint and resolves on success', async () => {
    const patched = vi.fn();
    server.use(
      http.patch('http://localhost/api/sep/admin/settings/SEPSettings', async ({ request }) => {
        patched(await request.json());
        return HttpResponse.json([{ ...sepListResponse.groups[0].settings[0], value: 9 }]);
      }),
    );

    const { result } = renderHook(() => usePatchSetting(), { wrapper: makeWrapper() });
    await result.current.mutateAsync({
      settingClass: 'SEPSettings',
      key: 'SYNC_REFRESH_TIME',
      value: 9,
    });

    expect(patched).toHaveBeenCalledWith({ SYNC_REFRESH_TIME: 9 });
  });

  it('surfaces the 422 body so settingErrorMessage can read it', async () => {
    server.use(
      http.patch('http://localhost/api/tasks/admin/settings/TasksSettings', () =>
        HttpResponse.json(
          {
            detail: [
              {
                loc: ['body', 'STALENESS_THRESHOLD_SECONDS', 'greater_than'],
                msg: 'Input should be greater than 0',
                type: 'greater_than',
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );

    const { result } = renderHook(() => usePatchSetting(), { wrapper: makeWrapper() });
    let caught: ApiError | undefined;
    await result.current
      .mutateAsync({ settingClass: 'TasksSettings', key: 'STALENESS_THRESHOLD_SECONDS', value: 0 })
      .catch((e: ApiError) => {
        caught = e;
      });

    expect(caught?.status).toBe(422);
    expect(settingErrorMessage(caught, 'STALENESS_THRESHOLD_SECONDS')).toBe(
      'Input should be greater than 0',
    );
  });
});

describe('useResetSetting', () => {
  it('DELETEs the per-key override endpoint', async () => {
    const deleted = vi.fn();
    server.use(
      http.delete(
        'http://localhost/api/tasks/admin/settings/TasksSettings/STALENESS_THRESHOLD_SECONDS',
        () => {
          deleted();
          return new HttpResponse(null, { status: 204 });
        },
      ),
    );

    const { result } = renderHook(() => useResetSetting(), { wrapper: makeWrapper() });
    await result.current.mutateAsync({
      settingClass: 'TasksSettings',
      key: 'STALENESS_THRESHOLD_SECONDS',
    });

    expect(deleted).toHaveBeenCalled();
  });
});
