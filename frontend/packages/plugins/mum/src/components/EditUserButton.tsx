import { useCallback, useMemo, useState } from 'react';
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
import { UserRolesEditor } from './UserRolesEditor';
import type { RoleEntry } from './UserRolesEditor';
import type { UserRow } from '../MumUserList';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';
import { useTaskStream } from '../useTaskStream';
import type { TaskStreamState } from '../useTaskStream';

const DEFAULT_DB = 'admin';

const parseRoles = (roles: unknown, defaultDb = DEFAULT_DB): RoleEntry[] => {
  if (!Array.isArray(roles)) return [];
  return (roles as unknown[]).flatMap((item) => {
    if (typeof item === 'string' && item) return [{ role: item, db: defaultDb }];
    if (item && typeof item === 'object') {
      const r = item as Record<string, unknown>;
      const role = String(r['role'] ?? r['name'] ?? '');
      if (!role) return [];
      return [{ role, db: String(r['db'] ?? defaultDb) }];
    }
    return [];
  });
};

interface EditUserButtonProps {
  row: UserRow;
  selectedTarget: string;
  builtinRoles: string[];
  rolesData?: RoleRow[];
  onSuccess?: (meta: { username: string; roles: RoleEntry[]; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

export function EditUserButton({
  row,
  selectedTarget,
  builtinRoles,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}: EditUserButtonProps) {
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
    } else if (s.status === 'error') {
      setError(s.message);
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, roles, userDb, selectedTarget, onSuccess]);

  const { stream } = useTaskStream({ onStateChange });

  const initialValues = useMemo(() => {
    const db = String(row?.['db'] ?? DEFAULT_DB);
    return {
      usernameValue: String(row?.['user'] ?? row?.['username'] ?? ''),
      rolesValue: parseRoles(row?.['roles'], db),
      dbValue: db,
    };
  }, [row]);

  const openDialog = () => {
    setUsername(initialValues.usernameValue);
    setRoles(initialValues.rolesValue);
    setUserDb(initialValues.dbValue);
    setPassword('');
    setError(null);
    setStreamState({ status: 'idle' });
    setOpen(true);
  };

  const closeDialog = () => { if (!loading) setOpen(false); };

  const handleSubmit = async () => {
    if (!selectedTarget) { setError('Select an executor host first.'); return; }
    if (!username) { setError('Username is required.'); return; }
    if (roles.length === 0) { setError('At least one role is required.'); return; }
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        target: selectedTarget,
        username,
        db: userDb || DEFAULT_DB,
        roles,
      };
      if (password) body['password'] = password;
      const resp = await apiClient.post('/plugins/mum/ui/update-user', body);
      const historyId = (resp.data as Record<string, unknown>)?.['history'] as Record<string, unknown> | undefined;
      stream(historyId?.['id'] as string);
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to update user');
      setLoading(false);
    }
  };

  const running = streamState.status === 'running' || loading;

  return (
    <>
      <Button size="small" variant="outlined" onClick={openDialog} {...buttonProps}>EDIT</Button>
      <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="md" scroll="paper" disableScrollLock>
        <DialogTitle>Edit MongoDB user</DialogTitle>
        <DialogContent dividers sx={{ display: 'grid', gap: 2 }}>
          <TextField label="Username" value={username} disabled fullWidth />
          <TextField
            label="Password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={running}
            helperText="Leave blank to keep existing password"
            fullWidth
          />
          <UserRolesEditor
            builtinRoles={builtinRoles}
            customRoles={customRoles}
            value={roles}
            onChange={setRoles}
            defaultDb={userDb}
            disabled={running}
          />
          {streamState.status === 'running' && (
            <Typography variant="body2" color="text.secondary">Saving…</Typography>
          )}
          {error && (
            <Typography color="error" variant="body2" sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {error}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={running}>Cancel</Button>
          <Button onClick={handleSubmit} variant="contained" color="success" disabled={running}>
            {running ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
