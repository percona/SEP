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
import { useForm } from 'react-hook-form';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  List,
  ListItem,
  ListItemText,
  Radio,
  TextField,
  Typography,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import ErrorIcon from '@mui/icons-material/Error';
import RemoveCircleIcon from '@mui/icons-material/RemoveCircle';
import type { AlertBackupSummary, AlertTemplate, PushResult, WizardMode } from './types';
import { formatTimestamp } from './utils';
import { useDeletePagerDuty, usePushTemplates, useRestoreBackup, useSavePagerDuty } from './hooks';

// ── Push flow ─────────────────────────────────────────────────────────────────

interface PushFlowProps {
  templates: AlertTemplate[];
  onClose: () => void;
  onSuccess?: () => void;
}

function PushFlow({ templates, onClose, onSuccess }: PushFlowProps) {
  const [results, setResults] = useState<PushResult[] | null>(null);
  const pushMutation = usePushTemplates();

  const handlePush = async () => {
    try {
      const data = await pushMutation.mutateAsync({
        selectedTemplates: templates.map((t) => t.name),
      });
      setResults(data.results);
      // Clear the parent's selection so the just-pushed templates aren't left
      // checked (which would invite an accidental immediate re-push).
      onSuccess?.();
    } catch {
      // react-query sets isError; render handled above
    }
  };

  if (results !== null) {
    return (
      <>
        <DialogContent>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            Push results:
          </Typography>
          <List dense>
            {results.map((r) => (
              <ListItem key={r.name} disablePadding sx={{ gap: 1, mb: 0.5 }}>
                {r.status === 'success' && <CheckCircleIcon fontSize="small" color="success" />}
                {r.status === 'skipped' && <RemoveCircleIcon fontSize="small" color="warning" />}
                {r.status === 'error' && <ErrorIcon fontSize="small" color="error" />}
                <ListItemText
                  primary={r.name}
                  secondary={r.message}
                  primaryTypographyProps={{ variant: 'body2' }}
                  secondaryTypographyProps={{ variant: 'caption' }}
                />
              </ListItem>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </>
    );
  }

  return (
    <>
      <DialogContent>
        {pushMutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {pushMutation.error?.message ?? 'Push failed'}
          </Alert>
        )}
        <Typography variant="body2" sx={{ mb: 2 }}>
          Push {templates.length} template{templates.length !== 1 ? 's' : ''} to PMM:
        </Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
          {templates.map((t) => (
            <Chip key={t.name} label={t.name} size="small" variant="outlined" />
          ))}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={pushMutation.isPending}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={() => void handlePush()}
          disabled={pushMutation.isPending || templates.length === 0}
          startIcon={pushMutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {pushMutation.isPending ? 'Pushing…' : 'Push to PMM'}
        </Button>
      </DialogActions>
    </>
  );
}

// ── Restore flow ──────────────────────────────────────────────────────────────

interface RestoreFormValues {
  // Radio inputs yield string values from the DOM; coerce to number only at submit.
  backupId: string | null;
}

interface RestoreFlowProps {
  backups: AlertBackupSummary[];
  onClose: () => void;
}

function RestoreFlow({ backups, onClose }: RestoreFlowProps) {
  const { register, handleSubmit, watch } = useForm<RestoreFormValues>({
    defaultValues: { backupId: null },
  });
  const restoreMutation = useRestoreBackup();
  const [done, setDone] = useState(false);
  const selectedId = watch('backupId');

  const onSubmit = async (values: RestoreFormValues) => {
    if (values.backupId === null) {
      return;
    }
    try {
      await restoreMutation.mutateAsync({ backupId: Number(values.backupId) });
      setDone(true);
    } catch {
      // react-query sets isError; render handled above
    }
  };

  if (done) {
    return (
      <>
        <DialogContent>
          <Alert severity="success">Backup restored successfully.</Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </>
    );
  }

  return (
    <form onSubmit={(e) => void handleSubmit(onSubmit)(e)}>
      <DialogContent>
        {restoreMutation.isError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {restoreMutation.error?.message ?? 'Restore failed'}
          </Alert>
        )}
        {backups.length === 0 ? (
          <Alert severity="info">No backups available.</Alert>
        ) : (
          <>
            <Typography variant="body2" sx={{ mb: 1 }}>
              Select a backup to restore:
            </Typography>
            <List dense>
              {backups.map((b) => (
                <ListItem key={b.id} disablePadding>
                  <Radio
                    {...register('backupId')}
                    value={b.id}
                    size="small"
                    inputProps={{ 'aria-label': `Backup ${b.id}` }}
                  />
                  <ListItemText
                    primary={`Backup #${b.id}`}
                    secondary={formatTimestamp(b.created_at)}
                  />
                </ListItem>
              ))}
            </List>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={restoreMutation.isPending}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="contained"
          color="warning"
          disabled={restoreMutation.isPending || selectedId === null || backups.length === 0}
          startIcon={restoreMutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {restoreMutation.isPending ? 'Restoring…' : 'Restore'}
        </Button>
      </DialogActions>
    </form>
  );
}

// ── PagerDuty flow ────────────────────────────────────────────────────────────

interface PagerDutyFormValues {
  integrationKey: string;
}

interface PagerDutyFlowProps {
  configured: boolean;
  onClose: () => void;
}

function PagerDutyFlow({ configured, onClose }: PagerDutyFlowProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<PagerDutyFormValues>({ defaultValues: { integrationKey: '' } });

  const saveMutation = useSavePagerDuty();
  const deleteMutation = useDeletePagerDuty();
  const [result, setResult] = useState<string | null>(null);

  const onSave = async (values: PagerDutyFormValues) => {
    try {
      const res = await saveMutation.mutateAsync({ integrationKey: values.integrationKey });
      setResult(res.status === 'created' ? 'PagerDuty configured.' : 'PagerDuty updated.');
    } catch {
      // react-query sets isError; render handled above
    }
  };

  const onDelete = async () => {
    try {
      await deleteMutation.mutateAsync();
      setResult('PagerDuty contact point deleted.');
    } catch {
      // react-query sets isError; render handled above
    }
  };

  const isBusy = saveMutation.isPending || deleteMutation.isPending;

  if (result !== null) {
    return (
      <>
        <DialogContent>
          <Alert severity="success">{result}</Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Close</Button>
        </DialogActions>
      </>
    );
  }

  return (
    <form onSubmit={(e) => void handleSubmit(onSave)(e)}>
      <DialogContent>
        {(saveMutation.isError || deleteMutation.isError) && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {(saveMutation.error ?? deleteMutation.error)?.message ?? 'Operation failed'}
          </Alert>
        )}
        {configured && (
          <Alert severity="info" sx={{ mb: 2 }}>
            PagerDuty is already configured. Saving will update the integration key.
          </Alert>
        )}
        <TextField
          {...register('integrationKey', {
            required: 'Integration key is required',
            validate: (v) => v.trim().length > 0 || 'Integration key cannot be empty',
          })}
          label="PagerDuty Integration Key"
          fullWidth
          size="small"
          error={Boolean(errors.integrationKey)}
          helperText={errors.integrationKey?.message}
          type="password"
          autoComplete="off"
          inputProps={{ 'data-testid': 'pagerduty-key-input' }}
        />
        {configured && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="body2" color="text.secondary">
              Or remove the existing PagerDuty integration:
            </Typography>
            <Button
              variant="outlined"
              color="error"
              size="small"
              sx={{ mt: 1 }}
              onClick={() => void onDelete()}
              disabled={isBusy}
              startIcon={deleteMutation.isPending ? <CircularProgress size={16} /> : undefined}
            >
              {deleteMutation.isPending ? 'Deleting…' : 'Delete PagerDuty'}
            </Button>
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isBusy}>
          Cancel
        </Button>
        <Button
          type="submit"
          variant="contained"
          disabled={isBusy}
          startIcon={saveMutation.isPending ? <CircularProgress size={16} /> : undefined}
        >
          {saveMutation.isPending ? 'Saving…' : 'Save'}
        </Button>
      </DialogActions>
    </form>
  );
}

// ── Wizard shell ──────────────────────────────────────────────────────────────

const WIZARD_TITLES: Record<WizardMode, string> = {
  push: 'Push Templates to PMM',
  restore: 'Restore from Backup',
  pagerduty: 'Configure PagerDuty',
};

export interface AlertsWizardProps {
  mode: WizardMode;
  open: boolean;
  onClose: () => void;
  /** Templates selected for the push flow. */
  selectedTemplates?: AlertTemplate[];
  /** Available backups for the restore flow. */
  backups?: AlertBackupSummary[];
  /** Whether PagerDuty is already configured. */
  pagerdutyConfigured?: boolean;
  /** Called after a push succeeds (e.g. to clear the list-page selection). */
  onPushSuccess?: () => void;
}

/**
 * Multi-mode wizard dialog.
 *
 * The `mode` prop drives conditional branching:
 *  - push      → PushFlow (confirm selected templates → push → results)
 *  - restore   → RestoreFlow (select backup → restore → result)
 *  - pagerduty → PagerDutyFlow (enter key → save/delete → result)
 */
export function AlertsWizard({
  mode,
  open,
  onClose,
  selectedTemplates = [],
  backups = [],
  pagerdutyConfigured = false,
  onPushSuccess,
}: AlertsWizardProps) {
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{WIZARD_TITLES[mode]}</DialogTitle>

      {/* Conditional branching: each mode renders a different form flow */}
      {mode === 'push' && (
        <PushFlow templates={selectedTemplates} onClose={onClose} onSuccess={onPushSuccess} />
      )}
      {mode === 'restore' && <RestoreFlow backups={backups} onClose={onClose} />}
      {mode === 'pagerduty' && <PagerDutyFlow configured={pagerdutyConfigured} onClose={onClose} />}
    </Dialog>
  );
}
