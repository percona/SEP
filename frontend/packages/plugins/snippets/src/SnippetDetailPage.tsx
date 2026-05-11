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

import { useCallback, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Link as MuiLink,
  Tooltip,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import DownloadIcon from '@mui/icons-material/Download';
import {
  SchemaFormRenderer,
  TaskHistoryTable,
  TaskLogViewer,
  type TaskHistoryEntry,
} from '@sep/framework';
import {
  useSnippetDownload,
  useSnippetExecution,
  useSnippetHistory,
  useSnippetSchema,
} from './hooks';

const EXECUTION_RESERVED_NAMES = new Set(['executor_host', 'sudo', 'script_preview']);

/**
 * Snippet detail page rendered at `/snippets/:filename`.
 *
 * Composes three panels: the execution form (which embeds the script
 * preview as the per-snippet schema's read-only `ScriptPreviewField`),
 * and the per-snippet execution history table. The legacy Jinja2 detail
 * page remains mounted for capabilities not yet ported (chaining,
 * scheduling, alerting); the deprecation header reminds clients of the
 * impending removal.
 */
export function SnippetDetailPage() {
  const { filename } = useParams<{ filename: string }>();
  const navigate = useNavigate();

  const schemaQuery = useSnippetSchema(filename);
  const historyQuery = useSnippetHistory(filename);
  const executionMutation = useSnippetExecution(filename);
  const downloadMutation = useSnippetDownload(filename);

  const [logsEntry, setLogsEntry] = useState<TaskHistoryEntry | null>(null);

  const handleSubmit = (values: Record<string, unknown>) => {
    if (!filename) {
      return;
    }
    const args: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      if (EXECUTION_RESERVED_NAMES.has(key)) {
        continue;
      }
      if (value === '' || value === undefined) {
        continue;
      }
      args[key] = value;
    }
    // Stay on the snippet detail page after execute — `useSnippetExecution`
    // invalidates the per-snippet history query on success so the new run
    // appears in the table without navigating away (mirrors legacy Jinja2
    // behaviour and avoids the placeholder /tasks/* React route).
    executionMutation.mutate({
      executor_host: String(values.executor_host ?? ''),
      sudo: Boolean(values.sudo ?? false),
      args,
    });
  };

  const handleViewLogs = useCallback((entry: TaskHistoryEntry) => {
    setLogsEntry(entry);
  }, []);

  const handleCloseLogs = useCallback(() => {
    setLogsEntry(null);
  }, []);

  const submitError = executionMutation.isError
    ? (executionMutation.error?.message ?? 'Execution failed')
    : null;

  const handleDownload = useCallback(() => {
    if (!filename) {
      return;
    }
    downloadMutation.mutate();
  }, [filename, downloadMutation]);

  const downloadError = downloadMutation.isError
    ? (downloadMutation.error?.message ?? 'Download failed')
    : null;

  if (!filename) {
    return <Alert severity="error">Missing snippet filename in the URL.</Alert>;
  }

  if (schemaQuery.isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (schemaQuery.error || !schemaQuery.data) {
    return (
      <Alert severity="error">
        Failed to load snippet schema: {schemaQuery.error?.message ?? 'unknown error'}
      </Alert>
    );
  }

  return (
    <Box>
      <MuiLink
        component="button"
        type="button"
        onClick={() => navigate('..')}
        sx={{ mb: 2, display: 'inline-block' }}
      >
        ← Back to snippets
      </MuiLink>
      <Box
        sx={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 2,
          mb: 1,
        }}
      >
        <Typography variant="h4">{schemaQuery.data.display_name}</Typography>
        <Tooltip title={`Download ${filename}`}>
          <span>
            <IconButton
              aria-label={`Download ${filename}`}
              onClick={handleDownload}
              disabled={downloadMutation.isPending}
              size="small"
            >
              {downloadMutation.isPending ? <CircularProgress size={20} /> : <DownloadIcon />}
            </IconButton>
          </span>
        </Tooltip>
      </Box>
      {schemaQuery.data.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {schemaQuery.data.description}
        </Typography>
      )}
      {downloadError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => downloadMutation.reset()}>
          Failed to download snippet: {downloadError}
        </Alert>
      )}

      <SchemaFormRenderer
        sections={schemaQuery.data.forms ?? []}
        onSubmit={handleSubmit}
        submitLabel="Execute"
        loading={executionMutation.isPending}
        submitError={submitError}
      />

      <Divider sx={{ my: 4 }} />

      <Typography variant="h6" sx={{ mb: 1 }}>
        Execution history
      </Typography>
      {historyQuery.error ? (
        <Alert severity="error">
          Failed to load execution history: {historyQuery.error.message}
        </Alert>
      ) : (
        <TaskHistoryTable
          data={historyQuery.data?.items ?? []}
          isLoading={historyQuery.isLoading}
          hideTaskNameColumn
          onViewLogs={handleViewLogs}
        />
      )}

      <Dialog
        open={logsEntry !== null}
        onClose={handleCloseLogs}
        fullWidth
        maxWidth="lg"
        aria-labelledby="snippet-task-logs-title"
      >
        <DialogTitle
          id="snippet-task-logs-title"
          sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}
        >
          <span>
            Task logs
            {logsEntry?.task?.name ? ` — ${logsEntry.task.name}` : ''}
            {logsEntry?.id !== null && logsEntry?.id !== undefined ? ` #${logsEntry.id}` : ''}
          </span>
          <IconButton aria-label="Close logs dialog" onClick={handleCloseLogs} size="small">
            <CloseIcon fontSize="small" />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0 }}>
          {logsEntry?.id !== null && logsEntry?.id !== undefined ? (
            <TaskLogViewer
              taskHistoryId={logsEntry.id}
              taskStatus={logsEntry.status}
              height={520}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </Box>
  );
}
