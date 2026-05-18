import { useState } from 'react';
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
import type { UserRow } from '../MumUserList';
import type { ButtonProps } from '@mui/material';

const DEFAULT_DB = 'admin';

interface DeleteUserButtonProps {
  row: UserRow;
  selectedTarget: string;
  onSuccess?: (meta: { username: string; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

export function DeleteUserButton({ row, selectedTarget, onSuccess, buttonProps = {} }: DeleteUserButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState('');

  const username = String(row?.['user'] ?? row?.['username'] ?? '');
  const dbName = String(row?.['db'] ?? DEFAULT_DB);

  const handleOpen = () => { setConfirmText(''); setError(null); setOpen(true); };
  const handleClose = () => { if (!loading) setOpen(false); };

  const handleDelete = async () => {
    if (!selectedTarget) { setError('Select an executor host first.'); return; }
    if (confirmText !== username) { setError(`Type "${username}" to proceed.`); return; }
    setLoading(true);
    setError(null);
    try {
      await apiClient.post('/mum/ui/delete-user', { target: selectedTarget, username, db: dbName || DEFAULT_DB });
      setOpen(false);
      onSuccess?.({ username, db: dbName || DEFAULT_DB, target: selectedTarget });
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to delete user');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button size="small" color="error" variant="outlined" onClick={handleOpen} {...buttonProps}>DELETE</Button>
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs" disableScrollLock>
        <DialogTitle>Delete MongoDB user</DialogTitle>
        <DialogContent sx={{ display: 'grid', gap: 2, pt: 2 }}>
          <Typography variant="body2">
            You are about to delete user <strong>{username}</strong> from DB <code>{dbName}</code>.
          </Typography>
          <TextField
            label={`Type ${username} to proceed`}
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            disabled={loading}
            fullWidth
          />
          {error && <Typography color="error" variant="body2">{error}</Typography>}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={loading}>Cancel</Button>
          <Button onClick={handleDelete} variant="contained" color="error" disabled={loading}>
            {loading ? 'Deleting…' : 'Delete'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
