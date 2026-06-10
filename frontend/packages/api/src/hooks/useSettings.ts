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

/**
 * React Query hooks for the runtime Settings admin API (SEP-983).
 *
 * The settings surface is split across two FastAPI sub-apps:
 *   - `/api/sep/admin/settings`   — SEPSettings, SnippetsSettings, MessagesSettings
 *   - `/api/tasks/admin/settings` — TasksSettings
 *
 * `useSettingsList` fans out to both endpoints in parallel and merges their
 * `groups` client-side into a single class-keyed list. The two endpoints expose
 * disjoint setting classes, so the merge is a concatenation in a stable order.
 *
 * All request/response shapes come from the generated OpenAPI types — this file
 * never hand-rolls an API model.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { apiClient } from '../client';
import type { ApiError } from '../errors';
import type { components } from '../generated/sep';

// The settings models are declared identically in both the `sep` and `tasks`
// specs; we treat the `sep` copy as the canonical source for the shared shapes.
export type SettingClass = components['schemas']['SettingClassEnum'];
export type ReloadClassification = components['schemas']['ReloadClassification'];
export type SettingResponse = components['schemas']['SettingResponse'];
export type SettingClassGroup = components['schemas']['SettingClassGroup'];
export type SettingsListResponse = components['schemas']['SettingsListResponse'];
export type SettingsPatch = components['schemas']['SettingsPatch'];

/** The redacted literal the API returns in place of a secret value. */
export const REDACTED_SECRET = '**********';

/**
 * Setting classes served by the Tasks sub-app; everything else is on SEP.
 *
 * MAINTENANCE: this is the single source of truth for PATCH/DELETE routing. If
 * the Tasks sub-app ever registers a new settings class, add it here — otherwise
 * its mutations would be silently routed to the SEP endpoint and 404.
 */
const TASKS_CLASSES: ReadonlySet<SettingClass> = new Set(['TasksSettings']);

/** Base path (relative to the axios client's `/api` baseURL) for a class. */
function settingsBase(settingClass: SettingClass): string {
  return TASKS_CLASSES.has(settingClass) ? '/tasks/admin/settings' : '/sep/admin/settings';
}

export const SETTINGS_QUERY_KEY = ['settings', 'list'] as const;

const SETTINGS_ENDPOINTS = ['/sep/admin/settings/', '/tasks/admin/settings/'] as const;

/**
 * Fetch every overridable settings class from both sub-apps and merge the
 * responses into a single, stably-ordered group list keyed by `setting_class`.
 *
 * Both sub-apps ship together, so a single `Promise.all` (all-or-nothing) is
 * intentional — there is no partial-availability mode to degrade into. Pass
 * `enabled: false` to skip fetching entirely (e.g. for non-admin viewers).
 */
export function useSettingsList(options: { enabled?: boolean } = {}) {
  return useQuery<SettingClassGroup[], ApiError>({
    queryKey: SETTINGS_QUERY_KEY,
    enabled: options.enabled ?? true,
    queryFn: async () => {
      const responses = await Promise.all(
        SETTINGS_ENDPOINTS.map((url) => apiClient.get<SettingsListResponse>(url)),
      );

      // Merge by class. Endpoints are disjoint today, but de-dupe defensively so
      // a class that ever appears on both is collapsed (last write wins) rather
      // than rendered twice.
      const byClass = new Map<SettingClass, SettingClassGroup>();
      for (const { data } of responses) {
        for (const group of data.groups) {
          byClass.set(group.setting_class, group);
        }
      }
      return Array.from(byClass.values());
    },
    staleTime: 30 * 1000,
  });
}

interface ValidationErrorItem {
  loc?: unknown[];
  msg?: string;
}

/**
 * Pull the Pydantic validation message(s) for a single field out of a 422
 * {@link ApiError} body. Returns `null` when the error is not a 422, has no
 * structured `detail`, or none of the entries reference `key`. FastAPI reports
 * each failure as `{ loc: ['body', key, ...], msg }`, so we match on `loc`
 * containing the field name and join all matching messages.
 */
export function settingErrorMessage(
  error: ApiError | null | undefined,
  key: string,
): string | null {
  if (!error || error.status !== 422) {
    return null;
  }
  const detail = (error.data as { detail?: unknown } | undefined)?.detail;
  if (!Array.isArray(detail)) {
    return null;
  }
  const messages = (detail as ValidationErrorItem[])
    .filter((item) => Array.isArray(item.loc) && item.loc.includes(key))
    .map((item) => item.msg)
    .filter((msg): msg is string => typeof msg === 'string');
  return messages.length > 0 ? messages.join('; ') : null;
}

export interface PatchSettingVars {
  settingClass: SettingClass;
  key: string;
  value: unknown;
}

/**
 * Persist a single setting override via PATCH to its owning sub-app.
 *
 * The endpoint accepts a multi-key payload, but this hook ships the per-setting
 * shape `{ [key]: value }`. On success the list query is invalidated so the
 * rendered value reflects what the backend stored (e.g. a re-redacted secret).
 * On failure the rejected {@link ApiError} carries the raw response body, so a
 * 422 caller can read `error.data.detail` for the per-field Pydantic message.
 */
export function usePatchSetting() {
  const queryClient = useQueryClient();
  return useMutation<SettingResponse[], ApiError, PatchSettingVars>({
    mutationFn: async ({ settingClass, key, value }) => {
      const body: SettingsPatch = { [key]: value as SettingsPatch[string] };
      const { data } = await apiClient.patch<SettingResponse[]>(
        `${settingsBase(settingClass)}/${settingClass}`,
        body,
      );
      return data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY });
    },
  });
}

export interface ResetSettingVars {
  settingClass: SettingClass;
  key: string;
}

/**
 * Remove a setting's override via DELETE, reverting it to its declared default.
 * Idempotent on the backend; the list query is invalidated on success.
 */
export function useResetSetting() {
  const queryClient = useQueryClient();
  return useMutation<void, ApiError, ResetSettingVars>({
    mutationFn: async ({ settingClass, key }) => {
      await apiClient.delete(`${settingsBase(settingClass)}/${settingClass}/${key}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SETTINGS_QUERY_KEY });
    },
  });
}
