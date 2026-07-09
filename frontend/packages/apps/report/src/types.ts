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

export interface ReportParams {
  since: string;
  until: string;
  full: boolean;
  refresh: boolean;
  sections?: string[];
}

export interface ReportMetadata {
  title: string;
  generated_at: string;
  report_week: string;
  report_interval: string;
}

export interface MonitoredSummary {
  total_nodes: number;
  total_services: number;
  services_by_type: Record<string, number>;
}

export interface AdvisorCheck {
  name: string;
  description: string;
  summary: string;
  family?: string | null;
}

export interface FailedCheck {
  name: string;
  description: string;
  summary: string;
  severity: string;
  node_name?: string | null;
  node_id?: string | null;
  service_name?: string | null;
  service_id?: string | null;
  read_more_url: string;
}

export interface AdvisorFamily {
  family_key: string;
  display_name: string;
  checks: AdvisorCheck[];
  failed: Record<string, FailedCheck[]>;
}

export interface AdvisorSection {
  total_checks: number;
  total_failed: number;
  refresh_issues: string[];
  families: AdvisorFamily[];
}

export interface AlertSection {
  total_alerts: number;
  alerts_per_service: Record<string, number>;
  alerts_per_rule: Record<string, number>;
  alerts_per_host: Record<string, number>;
  alerts_daily: Record<string, number>;
}

export interface BackupEntry {
  id: string;
  alias: string;
  name: string;
  type: string;
  status: string;
  size: string;
  estimated_data: boolean;
  enabled?: boolean | null;
  encryption: string;
  period: Record<string, unknown>;
}

export interface BackupSection {
  total_backups: number;
  backups_by_host: Record<string, number>;
  backups_by_status: Record<string, number>;
  backups_by_type: Record<string, number>;
  failed_backups: BackupEntry[];
  all_backups: BackupEntry[];
}

export interface DiskUsageEntry {
  node_name: string;
  mountpoint: string;
  capacity_bytes: number;
  used_start_bytes: number;
  used_end_bytes: number;
  used_peak_bytes: number;
  usage_percentage: number;
}

export interface StorageSection {
  entries: DiskUsageEntry[];
}

export interface UptimeEntry {
  service_name: string;
  uptime: string;
  since: string;
}

export interface UptimeSection {
  entries: UptimeEntry[];
}

export interface InventoryEntry {
  service_name: string;
  service_type: string;
  node_name: string;
  status: string;
}

export interface InventorySection {
  entries: InventoryEntry[];
}

export interface ReportData {
  full: boolean;
  refresh: boolean;
  metadata: ReportMetadata;
  monitored: MonitoredSummary;
  advisors: AdvisorSection;
  alerts: AlertSection;
  backups: BackupSection;
  storage: StorageSection;
  uptime: UptimeSection;
  inventory: InventorySection;
}

export interface UploadResult {
  sys_id?: string;
  status: string;
  url?: string;
}

export interface ReportConfig {
  upload_disabled_reasons: string[];
}

export interface ReportJobResponse {
  job_id: string;
  status: string;
  pdf_ready: boolean;
  result?: UploadResult | Record<string, unknown> | null;
  error?: string | null;
}
