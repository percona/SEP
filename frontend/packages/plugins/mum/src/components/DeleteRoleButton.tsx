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
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';

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

  const roleName = String(row?.['role'] ?? row?.['name'] ?? '');
  const dbName = String(row?.['db'] ?? DEFAULT_DB);

  const handleOpen = () => { setConfirmText(''); setError(null); setOpen(true); };
  const handleClose = () => { if (!loading) setOpen(false); };

  const handleDelete = async () => {
    if (!selectedTarget) { setError('Select an executor host first.'); return; }
    if (confirmText !== roleName) { setError(`Type "${roleName}" to proceed.`); return; }
    setLoading(true);
    setError(null);
    try {
      await apiClient.post('/mum/ui/delete-role', { target: selectedTarget, role: roleName, db: dbName });
      setOpen(false);
      onSuccess?.({ role: roleName, db: dbName, target: selectedTarget });
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to delete role');
    } finally {
      setLoading(false);
    }
  };

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
