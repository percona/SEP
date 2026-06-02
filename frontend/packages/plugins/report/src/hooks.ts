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
import type { ReportConfig, ReportData, ReportParams, UploadResult } from './types';

// The PDF and upload endpoints do not accept a `sections` filter (the backend
// Form params for those routes omit it). Use this type to make the omission
// explicit rather than silently dropping it.
type ReportPdfParams = Omit<ReportParams, 'sections'>;

const API_BASE = '/plugins/report';

export function useGenerateReport(params: ReportParams | null) {
  return useQuery<ReportData>({
    queryKey: ['report', 'generate', params],
    queryFn: async () => {
      // params is guaranteed non-null when enabled (params !== null guard below)
      const p = params as ReportParams;
      const { data } = await apiClient.get<ReportData>(`${API_BASE}/generate/json`, {
        params: {
          since: p.since,
          until: p.until,
          full: p.full,
          refresh: p.refresh,
          ...(p.sections?.length ? { sections: p.sections } : {}),
        },
        // FastAPI's `sections: list[str] | None = Query()` only reads bracket-less
        // repeated params (`sections=advisors&sections=alerts`). Axios's default
        // serializer emits `sections[]=…`, which the backend ignores (binds None →
        // "all sections"). `indexes: null` drops the brackets so the filter applies.
        paramsSerializer: { indexes: null },
      });
      return data;
    },
    enabled: params !== null,
  });
}

export function useDownloadPdf() {
  return useMutation<void, Error, ReportPdfParams>({
    mutationFn: async (params) => {
      const body = new URLSearchParams({
        since: params.since,
        until: params.until,
        full: String(params.full),
        refresh: String(params.refresh),
      });
      const { data } = await apiClient.post<Blob>(`${API_BASE}/generate/pdf`, body, {
        responseType: 'blob',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      const url = URL.createObjectURL(data);
      try {
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'Health_and_Security_Report.pdf';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } finally {
        // Defer revocation: Safari and Firefox can race the anchor-triggered
        // download if the blob URL is revoked in the same tick as .click().
        setTimeout(() => URL.revokeObjectURL(url), 0);
      }
    },
  });
}

export function useUploadToServiceNow() {
  return useMutation<UploadResult, Error, ReportPdfParams>({
    mutationFn: async (params) => {
      const body = new URLSearchParams({
        since: params.since,
        until: params.until,
        full: String(params.full),
        refresh: String(params.refresh),
      });
      const { data } = await apiClient.post<UploadResult>(`${API_BASE}/upload`, body, {
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      });
      return data;
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
