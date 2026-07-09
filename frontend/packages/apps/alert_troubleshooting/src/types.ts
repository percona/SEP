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

export interface AlertSummary {
  name: string;
  label: string;
}

export interface AlertGroup {
  service_type: string;
  label: string;
  alerts: AlertSummary[];
}

export interface AlertInfo {
  name: string;
  label: string;
  service_type: string | null;
}

/** Intentional subset of SnippetResponse — alert troubleshooting only needs these four fields. */
export interface SnippetSummary {
  filename: string;
  title: string;
  description: string;
  is_approved: boolean;
}

export interface AlertDetailResponse {
  alert: AlertInfo;
  snippets: SnippetSummary[];
}
