import { useCallback, useState } from 'react';
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
import { UserRolesEditor } from './UserRolesEditor';
import type { RoleEntry } from './UserRolesEditor';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';
import { useTaskStream } from '../useTaskStream';
import type { TaskStreamState } from '../useTaskStream';

const DEFAULT_DB = 'admin';

interface AddDatabaseUserButtonProps {
  selectedTarget: string;
  builtinRoles: string[];
  rolesData?: RoleRow[];
  onSuccess?: (meta: { username: string; roles: RoleEntry[]; db: string; target: string }) => void;
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

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [roles, setRoles] = useState<RoleEntry[]>([]);
  const [userDb, setUserDb] = useState(DEFAULT_DB);
  const [streamState, setStreamState] = useState<TaskStreamState>({ status: 'idle' });

  const onStateChange = useCallback((s: TaskStreamState) => {
    setStreamState(s);
    if (s.status === 'success') {
      setOpen(false);
      onSuccess?.({ username, roles, db: userDb || DEFAULT_DB, target: selectedTarget });
      resetForm();
    } else if (s.status === 'error') {
      setError(s.message);
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, roles, userDb, selectedTarget, onSuccess]);

  const { stream } = useTaskStream({ onStateChange });

  const resetForm = () => {
    setUsername('');
    setPassword('');
    setRoles([]);
    setUserDb(DEFAULT_DB);
    setError(null);
    setStreamState({ status: 'idle' });
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
      const resp = await apiClient.post('/plugins/mum/ui/create-user', {
        target: selectedTarget,
        username,
        password,
        roles,
        db: userDb || DEFAULT_DB,
      });
      const historyId = (resp.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
      stream(historyId?.['id'] as string);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to create user');
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
          <TextField
            label="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={loading}
            required
            fullWidth
          />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={loading}
            required
            fullWidth
          />
          <TextField
            label="User database"
            value={userDb}
            onChange={(e) => setUserDb(e.target.value)}
            disabled={loading}
            helperText="Authentication database where this user account is created (e.g. admin)"
            fullWidth
          />
          <UserRolesEditor
            builtinRoles={builtinRoles}
            customRoles={customRoles}
            value={roles}
            onChange={setRoles}
            defaultDb={userDb}
            disabled={loading}
          />
          {streamState.status === 'running' && (
            <Typography variant="body2" color="text.secondary">Creating user…</Typography>
          )}
          {error && (
            <Typography color="error" variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {error}
            </Typography>
          )}
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
