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

import { useMutation, useQuery } from '@tanstack/react-query';
import { apiClient } from '@sep/api';
import { downloadBlob } from '@sep/framework';
import type {
  ReportConfig,
  ReportData,
  ReportJobResponse,
  ReportParams,
  UploadResult,
} from './types';

const API_BASE = '/plugins/report';
const POLL_INTERVAL_MS = 1_000;
const ACTIVE_JOB_STATES = new Set(['pending', 'received', 'started', 'retry']);
const TERMINAL_JOB_STATES = new Set(['success', 'failure', 'revoked']);

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function pollJob(
  jobPath: string,
  done: (job: ReportJobResponse) => boolean,
): Promise<ReportJobResponse> {
  for (;;) {
    const { data } = await apiClient.get<ReportJobResponse>(jobPath);
    const status = data.status.toLowerCase();
    if (status === 'success') {
      if (done(data)) {
        return data;
      }
      throw new Error(data.error || 'Report job completed without required result');
    }
    if (status === 'failure') {
      throw new Error(data.error || 'Report job failed');
    }
    if (status === 'revoked') {
      throw new Error(data.error || 'Report job was revoked');
    }
    if (!ACTIVE_JOB_STATES.has(status) && !TERMINAL_JOB_STATES.has(status)) {
      throw new Error(data.error || `Report job entered unexpected state: ${data.status}`);
    }
    await delay(POLL_INTERVAL_MS);
  }
}

export function useGenerateReport(params: ReportParams | null) {
  return useQuery<ReportData>({
    queryKey: ['report', 'generate', params],
    queryFn: async () => {
      const p = params as ReportParams;
      const { data } = await apiClient.get<ReportData>(`${API_BASE}/generate/json`, {
        params: {
          since: p.since,
          until: p.until,
          full: p.full,
          refresh: p.refresh,
          ...(p.sections?.length ? { sections: p.sections } : {}),
        },
        // FastAPI binds repeated bracket-less params: sections=a&sections=b.
        paramsSerializer: { indexes: null },
      });
      return data;
    },
    enabled: params !== null,
  });
}

export function useDownloadPdf() {
  return useMutation<void, Error, ReportData>({
    mutationFn: async (report) => {
      const { data: job } = await apiClient.post<ReportJobResponse>(`${API_BASE}/pdf-jobs`, {
        report,
      });
      await pollJob(
        `${API_BASE}/pdf-jobs/${job.job_id}`,
        (nextJob) => nextJob.status === 'success' && nextJob.pdf_ready,
      );
      const { data } = await apiClient.get<Blob>(`${API_BASE}/pdf-jobs/${job.job_id}/pdf`, {
        responseType: 'blob',
      });
      downloadBlob(data, 'Health_and_Security_Report.pdf');
    },
  });
}

export function useUploadToServiceNow() {
  return useMutation<UploadResult, Error, ReportData>({
    mutationFn: async (report) => {
      const { data: job } = await apiClient.post<ReportJobResponse>(`${API_BASE}/upload-jobs`, {
        report,
      });
      const finished = await pollJob(
        `${API_BASE}/upload-jobs/${job.job_id}`,
        (nextJob) => nextJob.status === 'success',
      );
      return (finished.result as UploadResult | null) ?? { status: 'uploaded' };
    },
  });
}

// Probe whether ServiceNow upload is configured. Returns empty disabled_reasons
// (upload enabled) on any error — 404 means endpoint not yet deployed (SEP-1059),
// other errors are transient config blips that should not silently block the user.
// SEP-1059 should expose GET /api/plugins/report/config with { upload_disabled_reasons }.
export function useReportConfig() {
  return useQuery<ReportConfig>({
    queryKey: ['report', 'config'],
    queryFn: async () => {
      try {
        const { data } = await apiClient.get<ReportConfig>(`${API_BASE}/config`);
        return data;
      } catch {
        return { upload_disabled_reasons: [] };
      }
    },
    staleTime: Infinity,
    retry: false,
  });
}
