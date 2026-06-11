import { useCallback, useState } from 'react';
import { apiClient } from '@sep/api';
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';
import { useTaskStream } from '../useTaskStream';
import type { TaskStreamState } from '../useTaskStream';

const DEFAULT_DB = 'admin';

interface DeleteRoleButtonProps {
  row: RoleRow;
  selectedTarget: string;
  onSuccess?: (meta: { role: string; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

export function DeleteRoleButton({ row, selectedTarget, onSuccess, buttonProps = {} }: DeleteRoleButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState('');
  const [streamState, setStreamState] = useState<TaskStreamState>({ status: 'idle' });

  const roleName = String(row?.['role'] ?? row?.['name'] ?? '');
  const dbName = String(row?.['db'] ?? DEFAULT_DB);

  const onStateChange = useCallback((s: TaskStreamState) => {
    setStreamState(s);
    if (s.status === 'success') {
      setOpen(false);
      onSuccess?.({ role: roleName, db: dbName, target: selectedTarget });
    } else if (s.status === 'error') {
      setError(s.message);
      setLoading(false);
    }
  }, [roleName, dbName, selectedTarget, onSuccess]);

  const { stream } = useTaskStream({ onStateChange });

  const handleOpen = () => { setConfirmText(''); setError(null); setStreamState({ status: 'idle' }); setOpen(true); };
  const handleClose = () => { if (!loading) setOpen(false); };

  const handleDelete = async () => {
    if (!selectedTarget) { setError('Select an executor host first.'); return; }
    if (confirmText !== roleName) { setError(`Type "${roleName}" to proceed.`); return; }
    setLoading(true);
    setError(null);
    try {
      const resp = await apiClient.post('/plugins/mum/ui/delete-role', { target: selectedTarget, role: roleName, db: dbName });
      const historyId = (resp.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
      stream(historyId?.['id'] as string);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to delete role');
      setLoading(false);
    }
  };

  const running = streamState.status === 'running' || loading;

  return (
    <>
      <Button size="small" color="error" variant="outlined" onClick={handleOpen} {...buttonProps}>DELETE</Button>
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs" disableScrollLock>
        <DialogTitle>Delete custom MongoDB role</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 2, pt: 2 }}>
          <Typography variant="body2">
            You are about to delete role <strong>{roleName}</strong> from DB <code>{dbName}</code>. This cannot be undone.
          </Typography>
          <TextField
            label={`Type ${roleName} to proceed`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            disabled={running}
            fullWidth
          />
          {running && streamState.status === 'running' && (
            <Typography variant="body2" color="text.secondary">Deleting…</Typography>
          )}
          {error && (
            <Typography color="error" variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {error}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={running}>Cancel</Button>
          <Button onClick={handleDelete} variant="contained" color="error" disabled={running}>
            {running ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
