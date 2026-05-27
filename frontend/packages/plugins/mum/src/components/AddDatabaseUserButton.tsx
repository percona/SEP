import { useState } from 'react';
import { apiClient } from '@sep/api';
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from '@mui/material';
import { BuiltinRolesSelector } from './BuiltinRolesSelector';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';

const DEFAULT_DB = 'admin';

interface AddDatabaseUserButtonProps {
  selectedTarget: string;
  builtinRoles: string[];
  rolesData?: RoleRow[];
  onSuccess?: (meta: { username: string; roles: unknown[]; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

export function AddDatabaseUserButton({
  selectedTarget,
  builtinRoles,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}: AddDatabaseUserButtonProps) {
  const customRoles = rolesData.filter((r) => !r.isBuiltin && r.role).map((r) => ({
    role: r.role as string,
    db: (r.db as string | undefined) ?? '',
  }));

  type RoleValue = string | { role: string; db: string };

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [roles, setRoles] = useState<RoleValue[]>([]);
  const [rolesDb, setRolesDb] = useState(DEFAULT_DB);

  const resetForm = () => {
    setUsername(''); setPassword(''); setRoles([]); setRolesDb(DEFAULT_DB); setError(null);
  };

  const handleOpen = () => { resetForm(); setOpen(true); };
  const handleClose = () => { if (!loading) setOpen(false); };

  const handleSubmit = async () => {
    if (!selectedTarget) { setError('Select an executor host first.'); return; }
    if (!username) { setError('Username is required.'); return; }
    if (!password || roles.length === 0) { setError('Password and at least one role are required.'); return; }
    setLoading(true);
    setError(null);
    try {
      // [MUM-REPLACE] begin — dispatch create-user task via SEP internal endpoint
      await apiClient.post('/mum/ui/create-user', {
        target: selectedTarget,
        username,
        password,
        roles,
        db: rolesDb || DEFAULT_DB,
      });
      // [MUM-REPLACE] end
      setOpen(false);
      onSuccess?.({ username, roles, db: rolesDb || DEFAULT_DB, target: selectedTarget });
      resetForm();
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to create user');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button variant="contained" color="success" onClick={handleOpen} {...buttonProps}>
        + add database user
      </Button>
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md" scroll="paper" disableScrollLock>
        <DialogTitle>Create MongoDB user</DialogTitle>
        <DialogContent dividers sx={{ display: 'grid', gap: 2 }}>
          <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} disabled={loading} required fullWidth />
          <TextField label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} disabled={loading} required fullWidth />
          <BuiltinRolesSelector
            builtinRoles={builtinRoles}
            customRoles={customRoles}
            value={roles}
            onChange={setRoles}
            disabled={loading}
          />
          <TextField
            label="Role database"
            value={rolesDb}
            onChange={(e) => setRolesDb(e.target.value)}
            disabled={loading}
            helperText="Database where roles apply (default admin)"
            fullWidth
          />
          {error && <Typography color="error" variant="body2">{error}</Typography>}
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose} disabled={loading}>Cancel</Button>
          <Box />
          <Button onClick={handleSubmit} variant="contained" color="success" disabled={loading}>
            {loading ? 'Creating…' : 'Create'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
