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

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Chip,
  Link,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material';
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline';
import RemoveCircleOutlineIcon from '@mui/icons-material/RemoveCircleOutline';
import {
  useSnippets,
  useApproveSnippet,
  useRemoveSnippetApproval,
  useBatchApproveSnippets,
} from './hooks';
import type { BatchApprovalErrorResponse, BatchApprovalResponse, SnippetResponse } from './types';

interface SnippetsListPageProps {
  isAdmin?: boolean;
}

interface BatchResult {
  success?: BatchApprovalResponse;
  error?: BatchApprovalErrorResponse;
  generic?: string;
}

function ApproveButton({ snippet }: { snippet: SnippetResponse }) {
  const approve = useApproveSnippet(snippet.filename);
  const removeApproval = useRemoveSnippetApproval(snippet.filename);
  const isPending = approve.isPending || removeApproval.isPending;
  const spinner = <CircularProgress size={16} color="inherit" />;

  if (snippet.is_approved) {
    return (
      <Tooltip title="Remove approval">
        <Button
          size="small"
          color="warning"
          startIcon={isPending ? spinner : <RemoveCircleOutlineIcon />}
          disabled={isPending}
          onClick={(e) => {
            e.stopPropagation();
            removeApproval.mutate();
          }}
        >
          Remove
        </Button>
      </Tooltip>
    );
  }

  return (
    <Tooltip title="Approve snippet">
      <Button
        size="small"
        color="success"
        startIcon={isPending ? spinner : <CheckCircleOutlineIcon />}
        disabled={isPending}
        onClick={(e) => {
          e.stopPropagation();
          approve.mutate();
        }}
      >
        Approve
      </Button>
    </Tooltip>
  );
}

/**
 * Snippet-centric list page rendered at `/snippets/`.
 *
 * Renders the snippet entities discovered by the backend (one row per
 * snippet file). When `isAdmin` is true, per-row approve / remove-approval
 * buttons and a multi-select batch-approve action are shown.
 */
export function SnippetsListPage({ isAdmin = false }: SnippetsListPageProps) {
  const navigate = useNavigate();
  const { data: snippets = [], isLoading, error } = useSnippets();
  const batchApprove = useBatchApproveSnippets();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);

  function toggleSelect(filename: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(filename)) {
        next.delete(filename);
      } else {
        next.add(filename);
      }
      return next;
    });
  }

  function toggleSelectAll() {
    if (selected.size === snippets.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(snippets.map((s) => s.filename)));
    }
  }

  function handleBatchApprove() {
    setBatchResult(null);
    batchApprove.mutate(
      { filenames: Array.from(selected) },
      {
        onSuccess: (data) => {
          setBatchResult({ success: data });
          setSelected(new Set());
        },
        onError: (err) => {
          if (err.response) {
            setBatchResult({ error: err.response });
          } else {
            setBatchResult({ generic: 'Batch approval failed. Please try again.' });
          }
        },
      },
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
      <Box sx={{ py: 4 }}>
        <Alert severity="error">Failed to load snippets: {error.message}</Alert>
      </Box>
    );
  }

  const allSelected = snippets.length > 0 && selected.size === snippets.length;
  const someSelected = selected.size > 0 && selected.size < snippets.length;

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Snippet Manager
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Pre-approved snippets discovered from disk. Click a row to view its execution form and
        history.
      </Typography>

      {batchResult?.success && (
        <Alert severity="success" onClose={() => setBatchResult(null)} sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1} flexWrap="wrap">
            <Chip label={`${batchResult.success.count} approved`} color="success" size="small" />
            {batchResult.success.skipped_already_approved.length > 0 && (
              <Chip
                label={`${batchResult.success.skipped_already_approved.length} already approved`}
                color="default"
                size="small"
              />
            )}
          </Stack>
        </Alert>
      )}

      {batchResult?.generic && (
        <Alert severity="error" onClose={() => setBatchResult(null)} sx={{ mb: 2 }}>
          {batchResult.generic}
        </Alert>
      )}

      {batchResult?.error && (
        <Alert severity="error" onClose={() => setBatchResult(null)} sx={{ mb: 2 }}>
          <Stack spacing={0.5}>
            {batchResult.error.missing_in_db.length > 0 && (
              <Box>
                <strong>Missing in database:</strong>{' '}
                {batchResult.error.missing_in_db.map((f) => (
                  <Chip key={f} label={f} size="small" sx={{ mr: 0.5 }} />
                ))}
              </Box>
            )}
            {batchResult.error.missing_on_disk.length > 0 && (
              <Box>
                <strong>Missing on disk:</strong>{' '}
                {batchResult.error.missing_on_disk.map((f) => (
                  <Chip key={f} label={f} size="small" sx={{ mr: 0.5 }} />
                ))}
              </Box>
            )}
          </Stack>
        </Alert>
      )}

      {isAdmin && selected.size > 0 && (
        <Box sx={{ mb: 2 }}>
          <Button
            variant="contained"
            color="success"
            onClick={handleBatchApprove}
            disabled={batchApprove.isPending}
          >
            Batch approve ({selected.size})
          </Button>
        </Box>
      )}

      {snippets.length === 0 ? (
        <Typography color="text.secondary">No snippets available.</Typography>
      ) : (
        <Table size="small">
          <TableHead>
            <TableRow>
              {isAdmin && (
                <TableCell padding="checkbox">
                  <Checkbox
                    indeterminate={someSelected}
                    checked={allSelected}
                    onChange={toggleSelectAll}
                    inputProps={{ 'aria-label': 'select all snippets' }}
                  />
                </TableCell>
              )}
              <TableCell>Filename</TableCell>
              <TableCell>Title</TableCell>
              <TableCell>Description</TableCell>
              <TableCell>Approved</TableCell>
              <TableCell>Reason</TableCell>
              {isAdmin && <TableCell>Actions</TableCell>}
            </TableRow>
          </TableHead>
          <TableBody>
            {snippets.map((snippet) => (
              <TableRow
                key={snippet.filename}
                hover
                sx={{ cursor: 'pointer' }}
                onClick={() => navigate(encodeURIComponent(snippet.filename))}
              >
                {isAdmin && (
                  <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selected.has(snippet.filename)}
                      onChange={() => toggleSelect(snippet.filename)}
                      inputProps={{ 'aria-label': `select ${snippet.filename}` }}
                    />
                  </TableCell>
                )}
                <TableCell>
                  <Link
                    component="button"
                    type="button"
                    underline="hover"
                    onClick={(event) => {
                      event.stopPropagation();
                      navigate(encodeURIComponent(snippet.filename));
                    }}
                  >
                    {snippet.filename}
                  </Link>
                </TableCell>
                <TableCell>{snippet.title}</TableCell>
                <TableCell>{snippet.description}</TableCell>
                <TableCell>{snippet.is_approved ? 'Yes' : 'No'}</TableCell>
                <TableCell>{snippet.reason}</TableCell>
                {isAdmin && (
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    <ApproveButton snippet={snippet} />
                  </TableCell>
                )}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Box>
  );
}
