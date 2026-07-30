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

import { useLocation, useNavigate } from 'react-router';
import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Link,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material';
import {
  isReportJobActive,
  reportJobError,
  uploadJobResult,
  useDownloadReportPdf,
  useGenerateReport,
  usePdfJob,
  useReportConfig,
  useStartPdfJob,
  useStartUploadJob,
  useUploadJob,
} from './hooks';
import type { ReportParams } from './types';

export function ReportResultPage() {
  const { state } = useLocation();
  const navigate = useNavigate();
  const params = (state as { params?: ReportParams } | null)?.params;
  const [pdfJobId, setPdfJobId] = useState<string | null>(null);
  const [downloadedPdfJobId, setDownloadedPdfJobId] = useState<string | null>(null);
  const [uploadJobId, setUploadJobId] = useState<string | null>(null);

  const { data: report, isLoading, error } = useGenerateReport(params ?? null);
  const { data: config } = useReportConfig();
  const startPdfJob = useStartPdfJob();
  const pdfJob = usePdfJob(pdfJobId);
  const downloadPdf = useDownloadReportPdf();
  const startUploadJob = useStartUploadJob();
  const uploadJob = useUploadJob(uploadJobId);

  const uploadDisabledReasons = config?.upload_disabled_reasons ?? [];
  const pdfInProgress =
    startPdfJob.isPending || isReportJobActive(pdfJob.data) || downloadPdf.isPending;
  const pdfResultError =
    pdfJob.data?.status.toLowerCase() === 'success' && !pdfJob.data.pdf_ready
      ? 'Report job completed without required result'
      : null;
  const pdfError =
    startPdfJob.error?.message ??
    pdfJob.error?.message ??
    pdfResultError ??
    reportJobError(pdfJob.data) ??
    downloadPdf.error?.message;
  const uploadInProgress = startUploadJob.isPending || isReportJobActive(uploadJob.data);
  const uploadResult = uploadJobResult(uploadJob.data);
  const uploadError =
    startUploadJob.error?.message ?? uploadJob.error?.message ?? reportJobError(uploadJob.data);
  const uploadDisabled =
    uploadInProgress || Boolean(uploadResult) || uploadDisabledReasons.length > 0;
  const uploadTooltip =
    uploadDisabledReasons.length > 0 ? uploadDisabledReasons.join('; ') : undefined;

  useEffect(() => {
    if (
      pdfJob.data?.status.toLowerCase() === 'success' &&
      pdfJob.data.pdf_ready &&
      downloadedPdfJobId !== pdfJob.data.job_id
    ) {
      setDownloadedPdfJobId(pdfJob.data.job_id);
      downloadPdf.mutate({ job: pdfJob.data });
    }
  }, [downloadPdf, downloadedPdfJobId, pdfJob.data]);

  if (!params) {
    return (
      <Alert severity="warning">
        No report parameters found. Please{' '}
        <Link
          component="button"
          type="button"
          onClick={() => navigate('/reports')}
          sx={{ verticalAlign: 'baseline' }}
        >
          go back
        </Link>{' '}
        and generate a report.
      </Alert>
    );
  }

  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return (
      <Alert severity="error">
        Failed to generate report: {error instanceof Error ? error.message : 'Unknown error'}
      </Alert>
    );
  }

  if (!report) {
    return null;
  }

  return (
    <Box sx={{ maxWidth: 800 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        {report.metadata.title || 'Health & Security Report'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {report.metadata.report_interval}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {report.metadata.report_week} · Generated{' '}
        {new Date(report.metadata.generated_at).toLocaleString()}
      </Typography>

      <Stack direction="row" spacing={1} sx={{ mb: 3 }} flexWrap="wrap" useFlexGap>
        <Chip label={`${report.monitored.total_nodes} nodes`} size="small" />
        <Chip label={`${report.monitored.total_services} services`} size="small" />
        <Chip
          label={`${report.advisors.total_failed} advisor ${report.advisors.total_failed === 1 ? 'failure' : 'failures'}`}
          size="small"
          color={report.advisors.total_failed > 0 ? 'error' : 'success'}
        />
        <Chip label={`${report.alerts.total_alerts} alerts`} size="small" />
        <Chip label={`${report.backups.total_backups} backups`} size="small" />
      </Stack>

      <Divider sx={{ mb: 3 }} />

      <Stack direction="row" spacing={2} sx={{ mb: 3 }} flexWrap="wrap" useFlexGap>
        <Button
          variant="contained"
          onClick={() => {
            setPdfJobId(null);
            setDownloadedPdfJobId(null);
            startPdfJob.mutate(report, {
              onSuccess: (job) => setPdfJobId(job.job_id),
            });
          }}
          disabled={pdfInProgress}
        >
          {pdfInProgress ? 'Generating PDF…' : 'Download PDF'}
        </Button>

        <Tooltip title={uploadTooltip}>
          <span>
            <Button
              variant="outlined"
              onClick={() => {
                setUploadJobId(null);
                startUploadJob.mutate(report, {
                  onSuccess: (job) => setUploadJobId(job.job_id),
                });
              }}
              disabled={uploadDisabled}
            >
              {uploadInProgress ? 'Uploading…' : 'Upload to ServiceNow'}
            </Button>
          </span>
        </Tooltip>

        <Button variant="text" onClick={() => navigate('/reports')}>
          Generate New Report
        </Button>
      </Stack>

      {pdfError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          PDF download failed: {pdfError}
        </Alert>
      )}

      {uploadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Upload failed: {uploadError}
        </Alert>
      )}

      {uploadResult && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Report uploaded to ServiceNow successfully.
        </Alert>
      )}

      {report.advisors.total_failed > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Advisor Failures ({report.advisors.total_failed})
          </Typography>
          {report.advisors.families.map((family) =>
            Object.keys(family.failed).length > 0 ? (
              <Box key={family.family_key} sx={{ mb: 2 }}>
                <Typography variant="subtitle1" fontWeight={500}>
                  {family.display_name}
                </Typography>
                {Object.entries(family.failed).map(([checkName, results]) =>
                  results.map((result, i) => (
                    <Box
                      key={`${checkName}-${i}`}
                      sx={{ ml: 2, mb: 0.5, display: 'flex', alignItems: 'center', gap: 1 }}
                    >
                      <Chip size="small" label={result.severity} color="error" />
                      <Typography variant="body2">{result.summary}</Typography>
                      {result.service_name && (
                        <Typography variant="body2" color="text.secondary">
                          · {result.service_name}
                        </Typography>
                      )}
                    </Box>
                  )),
                )}
              </Box>
            ) : null,
          )}
        </Box>
      )}

      {report.backups.failed_backups.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" sx={{ mb: 1 }}>
            Failed Backups ({report.backups.failed_backups.length})
          </Typography>
          {report.backups.failed_backups.map((backup) => (
            <Box key={backup.id} sx={{ mb: 0.5 }}>
              <Typography variant="body2">
                {backup.name}
                {backup.alias ? ` · ${backup.alias}` : ''}
                {backup.type ? ` · ${backup.type}` : ''}
              </Typography>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
