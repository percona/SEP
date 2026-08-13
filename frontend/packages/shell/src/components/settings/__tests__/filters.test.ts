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
import type { SettingClassGroup } from '@sep/api';

import {
  DEFAULT_SETTINGS_FILTERS,
  appLabelFor,
  filterSettingsGroups,
  partitionSettingsGroups,
} from '../filters';
import { makeSetting } from './fixtures';

const groups: SettingClassGroup[] = [
  {
    setting_class: 'SEPSettings',
    is_app_owned: false,
    settings: [
      makeSetting({ key: 'SYNC_REFRESH_TIME', reload: 'hot', has_override: true }),
      makeSetting({ key: 'STATIC_DIR', reload: 'not_overridable', has_override: false }),
      // Advanced yet hot — only the Advanced control should hide it.
      makeSetting({ key: 'FOOTER_TEMPLATE', reload: 'hot', is_advanced: true }),
      // Advanced and not_overridable — both dimensions hide it independently.
      makeSetting({ key: 'LEGACY_FLAG', reload: 'not_overridable', is_advanced: true }),
      // is_advanced left undefined, mimicking older API responses that omit the field.
      makeSetting({ key: 'PLAIN_FLAG', reload: 'hot', is_advanced: undefined }),
    ],
  },
  {
    setting_class: 'TasksSettings',
    is_app_owned: false,
    settings: [makeSetting({ setting_class: 'TasksSettings', key: 'STALENESS_THRESHOLD_SECONDS' })],
  },
];

const keysOf = (result: SettingClassGroup[]) => result.flatMap((g) => g.settings.map((s) => s.key));

describe('filterSettingsGroups', () => {
  it('keeps groups that still have matching settings under the default filters', () => {
    const result = filterSettingsGroups(groups, DEFAULT_SETTINGS_FILTERS);
    expect(result).toHaveLength(2);
  });

  it('defaults the reload filter to hot, hiding not_overridable settings', () => {
    expect(DEFAULT_SETTINGS_FILTERS.reload).toBe('hot');
    const result = filterSettingsGroups(groups, DEFAULT_SETTINGS_FILTERS);
    expect(keysOf(result)).not.toContain('STATIC_DIR');
  });

  it('keeps read-only-only app-owned groups visible under the default hot filter', () => {
    const readOnlyAppGroup: SettingClassGroup = {
      setting_class: 'HealthReportSettings',
      is_app_owned: true,
      app_id: 'report',
      app_enabled: true,
      settings: [
        makeSetting({
          setting_class: 'HealthReportSettings',
          key: 'upload',
          reload: 'not_overridable',
        }),
        makeSetting({
          setting_class: 'HealthReportSettings',
          key: 'endpoint',
          reload: 'not_overridable',
        }),
      ],
    };

    const result = filterSettingsGroups([readOnlyAppGroup], DEFAULT_SETTINGS_FILTERS);

    expect(result).toHaveLength(1);
    expect(keysOf(result)).toEqual(['upload', 'endpoint']);
  });

  it('hides advanced settings by default and reveals them when advanced is shown', () => {
    expect(DEFAULT_SETTINGS_FILTERS.advanced).toBe('hidden');
    const hidden = filterSettingsGroups(groups, DEFAULT_SETTINGS_FILTERS);
    expect(keysOf(hidden)).not.toContain('LEGACY_FLAG');

    const shown = filterSettingsGroups(groups, {
      ...DEFAULT_SETTINGS_FILTERS,
      reload: 'all',
      advanced: 'shown',
    });
    expect(keysOf(shown)).toContain('LEGACY_FLAG');
  });

  it('hides an advanced+hot setting by default and shows it once advanced is revealed', () => {
    // FOOTER_TEMPLATE is hot, so the hot reload default alone would keep it;
    // only the advanced dimension hides it.
    const hidden = filterSettingsGroups(groups, DEFAULT_SETTINGS_FILTERS);
    expect(keysOf(hidden)).not.toContain('FOOTER_TEMPLATE');

    const shown = filterSettingsGroups(groups, { ...DEFAULT_SETTINGS_FILTERS, advanced: 'shown' });
    expect(keysOf(shown)).toContain('FOOTER_TEMPLATE');
  });

  it('keeps settings whose is_advanced is absent, regardless of the advanced control', () => {
    const hidden = filterSettingsGroups(groups, DEFAULT_SETTINGS_FILTERS);
    expect(keysOf(hidden)).toContain('PLAIN_FLAG');
    const shown = filterSettingsGroups(groups, { ...DEFAULT_SETTINGS_FILTERS, advanced: 'shown' });
    expect(keysOf(shown)).toContain('PLAIN_FLAG');
  });

  it('filters by key substring, case-insensitively', () => {
    const result = filterSettingsGroups(groups, { ...DEFAULT_SETTINGS_FILTERS, search: 'sync' });
    expect(result).toHaveLength(1);
    expect(result[0].settings.map((s) => s.key)).toEqual(['SYNC_REFRESH_TIME']);
  });

  it('filters by setting class', () => {
    const result = filterSettingsGroups(groups, {
      ...DEFAULT_SETTINGS_FILTERS,
      settingClass: 'TasksSettings',
    });
    expect(result).toHaveLength(1);
    expect(result[0].setting_class).toBe('TasksSettings');
  });

  it('filters by reload classification', () => {
    const result = filterSettingsGroups(groups, {
      ...DEFAULT_SETTINGS_FILTERS,
      reload: 'not_overridable',
    });
    expect(result.flatMap((g) => g.settings.map((s) => s.key))).toEqual(['STATIC_DIR']);
  });

  it('filters by override presence', () => {
    const present = filterSettingsGroups(groups, { ...DEFAULT_SETTINGS_FILTERS, override: 'yes' });
    expect(present.flatMap((g) => g.settings.map((s) => s.key))).toEqual(['SYNC_REFRESH_TIME']);
    const absent = filterSettingsGroups(groups, { ...DEFAULT_SETTINGS_FILTERS, override: 'no' });
    expect(absent.flatMap((g) => g.settings.map((s) => s.key))).not.toContain('SYNC_REFRESH_TIME');
  });

  it('drops groups whose settings all filter out', () => {
    const result = filterSettingsGroups(groups, {
      ...DEFAULT_SETTINGS_FILTERS,
      search: 'nonexistent',
    });
    expect(result).toHaveLength(0);
  });
});

const appGroup = (
  overrides: Partial<SettingClassGroup> & Pick<SettingClassGroup, 'setting_class'>,
): SettingClassGroup => ({
  is_app_owned: true,
  settings: [makeSetting({ setting_class: overrides.setting_class, key: 'K' })],
  ...overrides,
});

describe('partitionSettingsGroups', () => {
  it('separates core groups from enabled app-owned groups', () => {
    const enabled = appGroup({
      setting_class: 'AlertsSettings',
      app_id: 'alerts',
      app_display_name: 'Alerts',
      app_enabled: true,
    });
    const { core, appOwned } = partitionSettingsGroups([...groups, enabled]);
    expect(core.map((g) => g.setting_class)).toEqual(['SEPSettings', 'TasksSettings']);
    expect(appOwned.map((g) => g.setting_class)).toEqual(['AlertsSettings']);
  });

  it('drops app-owned groups whose owning app is disabled or unset', () => {
    const disabled = appGroup({
      setting_class: 'AlertsSettings',
      app_id: 'alerts',
      app_enabled: false,
    });
    const unset = appGroup({ setting_class: 'InventorySettings', app_id: 'inventory' });
    const { core, appOwned } = partitionSettingsGroups([...groups, disabled, unset]);
    expect(core).toHaveLength(2);
    expect(appOwned).toHaveLength(0);
  });
});

describe('appLabelFor', () => {
  it('prefers the display name, falling back to the app id then undefined', () => {
    expect(
      appLabelFor(appGroup({ setting_class: 'AlertsSettings', app_display_name: 'Alerts' })),
    ).toBe('Alerts');
    expect(appLabelFor(appGroup({ setting_class: 'AlertsSettings', app_id: 'alerts' }))).toBe(
      'alerts',
    );
    expect(appLabelFor(appGroup({ setting_class: 'AlertsSettings' }))).toBeUndefined();
  });
});
