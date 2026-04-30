import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Alert,
  Box,
  CircularProgress,
  Divider,
  Link as MuiLink,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { SchemaFormRenderer } from '@sep/framework';
import { useSnippetExecution, useSnippetHistory, useSnippetSchema } from './hooks';

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
    executionMutation.mutate(
      {
        executor_host: String(values.executor_host ?? ''),
        sudo: Boolean(values.sudo ?? false),
        args,
      },
      {
        onSuccess: (response) => {
          if (response.task_id !== null) {
            navigate(`/tasks/${response.task_id}`);
          }
        },
      },
    );
  };

  const submitError = useMemo(() => {
    if (!executionMutation.isError) {
      return null;
    }
    return executionMutation.error?.message ?? 'Execution failed';
  }, [executionMutation.isError, executionMutation.error]);

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
      <Typography variant="h4" sx={{ mb: 1 }}>
        {schemaQuery.data.displayName}
      </Typography>
      {schemaQuery.data.description && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {schemaQuery.data.description}
        </Typography>
      )}

      <SchemaFormRenderer
        sections={schemaQuery.data.forms}
        onSubmit={handleSubmit}
        submitLabel="Execute"
        loading={executionMutation.isPending}
        submitError={submitError}
      />

      <Divider sx={{ my: 4 }} />

      <Typography variant="h6" sx={{ mb: 1 }}>
        Execution history
      </Typography>
      {historyQuery.isLoading ? (
        <CircularProgress size={20} />
      ) : historyQuery.error ? (
        <Alert severity="error">
          Failed to load execution history: {historyQuery.error.message}
        </Alert>
      ) : (historyQuery.data ?? []).length === 0 ? (
        <Typography color="text.secondary">No executions yet.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Run</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Started</TableCell>
              <TableCell>By</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {(historyQuery.data ?? []).map((row) => (
              <TableRow key={row.task_id} hover>
                <TableCell>
                  <MuiLink
                    component="button"
                    type="button"
                    onClick={() => navigate(`/tasks/${row.task_id}`)}
                  >
                    #{row.task_id}
                  </MuiLink>
                </TableCell>
                <TableCell>{row.status}</TableCell>
                <TableCell>{row.created_at}</TableCell>
                <TableCell>{row.created_by ?? '—'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Box>
  );
}
