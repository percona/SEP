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

import type { SettingClassGroup } from '@sep/api';

export interface SettingsFilters {
  /** Case-insensitive substring matched against the setting key. */
  search: string;
  /** A specific setting_class, or `'all'`. */
  settingClass: string;
  reload: 'all' | 'hot' | 'not_overridable';
  override: 'all' | 'yes' | 'no';
  /**
   * Whether settings flagged `is_advanced` are hidden (default) or revealed.
   * Advanced settings are rarely changed and easy to misconfigure, so the
   * everyday view keeps them out of sight.
   */
  advanced: 'hidden' | 'shown';
}

export const DEFAULT_SETTINGS_FILTERS: SettingsFilters = {
  search: '',
  settingClass: 'all',
  reload: 'hot',
  override: 'all',
  advanced: 'hidden',
};

/**
 * Apply the search box and filter panel to the merged group list. Groups whose
 * settings all filter out are dropped so the UI doesn't render empty sections.
 */
export function filterSettingsGroups(
  groups: SettingClassGroup[],
  filters: SettingsFilters,
): SettingClassGroup[] {
  const needle = filters.search.trim().toLowerCase();
  return groups
    .filter(
      (group) => filters.settingClass === 'all' || group.setting_class === filters.settingClass,
    )
    .map((group) => ({
      ...group,
      settings: group.settings.filter((setting) => {
        if (needle && !setting.key.toLowerCase().includes(needle)) {
          return false;
        }
        if (filters.advanced === 'hidden' && setting.is_advanced) {
          return false;
        }
        if (filters.reload !== 'all' && setting.reload !== filters.reload) {
          return false;
        }
        if (filters.override === 'yes' && !setting.has_override) {
          return false;
        }
        if (filters.override === 'no' && setting.has_override) {
          return false;
        }
        return true;
      }),
    }))
    .filter((group) => group.settings.length > 0);
}

export interface PartitionedSettingsGroups {
  /** Core SEP settings groups, rendered in the main region. */
  core: SettingClassGroup[];
  /** App-owned groups whose owning app is enabled, rendered under "App settings". */
  appOwned: SettingClassGroup[];
}

/**
 * Split the given groups into core and app-owned regions. App-owned
 * groups whose owning app is disabled or not enabled are dropped entirely, so the
 * page never shows settings for apps the admin is not running. Core groups are
 * always kept regardless of any app metadata.
 */
export function partitionSettingsGroups(groups: SettingClassGroup[]): PartitionedSettingsGroups {
  const core: SettingClassGroup[] = [];
  const appOwned: SettingClassGroup[] = [];
  for (const group of groups) {
    if (!group.is_app_owned) {
      core.push(group);
    } else if (group.app_enabled) {
      appOwned.push(group);
    }
  }
  return { core, appOwned };
}

/** The display label for an app-owned group's owning app, or `undefined`. */
export function appLabelFor(group: SettingClassGroup): string | undefined {
  return group.app_display_name ?? group.app_id ?? undefined;
}
