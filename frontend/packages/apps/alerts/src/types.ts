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

export type AlertSeverity = 'info' | 'warning' | 'critical';

/** The three wizard flows, each rendering different form fields and steps. */
export type WizardMode = 'push' | 'restore' | 'pagerduty';

export interface AlertTemplate {
  name: string;
  service_type: string;
  expression: string;
  default_threshold: number;
  severity: AlertSeverity;
  description: string;
  summary: string;
  /** True when the template is already present in PMM. */
  in_pmm: boolean;
}

export interface AlertTemplateGroup {
  service_type: string;
  label: string;
  templates: AlertTemplate[];
}

export interface PagerDutyStatus {
  configured: boolean;
  uid: string | null;
}

export interface AlertBackupSummary {
  id: number;
  created_at: string;
}

/** Shape returned by GET /api/apps/alerts/ (the alerts index endpoint). */
export interface AlertIndexResponse {
  groups: AlertTemplateGroup[];
  pmm_connected: boolean;
  pagerduty: PagerDutyStatus | null;
  recent_backups: AlertBackupSummary[];
}

export interface PushResult {
  name: string;
  status: 'success' | 'skipped' | 'error';
  message: string;
}

export interface PushResponse {
  results: PushResult[];
}

export interface AlertBackupDetail {
  id: number;
  created_at: string;
  templates: Array<{ name: string; summary: string }>;
  rules: Array<{ title: string }>;
  contact_points: Array<{ name: string; type: string }>;
  folders: Array<{ title: string }>;
  notification_policy_receiver: string | null;
}
