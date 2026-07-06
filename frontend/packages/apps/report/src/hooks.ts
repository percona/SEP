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

const API_BASE = '/apps/report';
const REPORT_JOB_POLL_INTERVAL_MS = 1_000;
const DEFAULT_PDF_FILENAME = 'Health_and_Security_Report.pdf';
const ACTIVE_JOB_STATES = new Set(['pending', 'received', 'started', 'retry']);

function filenameFromContentDisposition(header: string | undefined): string | null {
  const match = /filename="([^"]+)"/.exec(header ?? '');
  return match?.[1] ?? null;
}

function filenameFromJob(job: ReportJobResponse | null | undefined): string | null {
  const filename = (job?.result as Record<string, unknown> | null | undefined)?.filename;
  return typeof filename === 'string' && filename.trim() ? filename : null;
}

function reportJobPath(kind: 'pdf' | 'upload', jobId: string): string {
  return `${API_BASE}/${kind === 'pdf' ? 'pdf-jobs' : 'upload-jobs'}/${jobId}`;
}

export function isReportJobActive(job: ReportJobResponse | null | undefined): boolean {
  return ACTIVE_JOB_STATES.has(job?.status.toLowerCase() ?? '');
}

export function reportJobError(job: ReportJobResponse | null | undefined): string | null {
  const status = job?.status.toLowerCase();
  if (status === 'failure') {
    return job?.error || 'Report job failed';
  }
  if (status === 'revoked') {
    return job?.error || 'Report job was revoked';
  }
  if (status && status !== 'success' && !ACTIVE_JOB_STATES.has(status)) {
    return job?.error || `Report job entered unexpected state: ${job?.status}`;
  }
  return null;
}

function useReportJob(kind: 'pdf' | 'upload', jobId: string | null) {
  return useQuery<ReportJobResponse>({
    queryKey: ['report', kind, 'job', jobId],
    enabled: Boolean(jobId),
    queryFn: async () => {
      const { data } = await apiClient.get<ReportJobResponse>(reportJobPath(kind, jobId as string));
      return data;
    },
    refetchInterval: (query) =>
      isReportJobActive(query.state.data) ? REPORT_JOB_POLL_INTERVAL_MS : false,
  });
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

export function useStartPdfJob() {
  return useMutation<ReportJobResponse, Error, ReportData>({
    mutationFn: async (report) => {
      const { data: job } = await apiClient.post<ReportJobResponse>(`${API_BASE}/pdf-jobs`, {
        report,
      });
      return job;
    },
  });
}

export function usePdfJob(jobId: string | null) {
  return useReportJob('pdf', jobId);
}

export function useDownloadReportPdf() {
  return useMutation<void, Error, { job: ReportJobResponse }>({
    mutationFn: async ({ job }) => {
      if (job.status.toLowerCase() !== 'success' || !job.pdf_ready) {
        throw new Error(reportJobError(job) || 'PDF is not ready');
      }
      const response = await apiClient.get<Blob>(`${API_BASE}/pdf-jobs/${job.job_id}/pdf`, {
        responseType: 'blob',
      });
      const filename =
        filenameFromContentDisposition(response.headers['content-disposition']) ??
        filenameFromJob(job) ??
        DEFAULT_PDF_FILENAME;
      downloadBlob(response.data, filename);
    },
  });
}

export function useStartUploadJob() {
  return useMutation<ReportJobResponse, Error, ReportData>({
    mutationFn: async (report) => {
      const { data: job } = await apiClient.post<ReportJobResponse>(`${API_BASE}/upload-jobs`, {
        report,
      });
      return job;
    },
  });
}

export function useUploadJob(jobId: string | null) {
  return useReportJob('upload', jobId);
}

export function uploadJobResult(job: ReportJobResponse | null | undefined): UploadResult | null {
  if (job?.status.toLowerCase() !== 'success') {
    return null;
  }
  return (job.result as UploadResult | null) ?? { status: 'uploaded' };
}

// Probe whether ServiceNow upload is configured. Returns empty disabled_reasons
// (upload enabled) on any error — 404 means the config endpoint is not yet
// deployed, other errors are transient config blips that should not silently
// block the user. The endpoint should expose GET /api/apps/report/config with
// { upload_disabled_reasons }.
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
