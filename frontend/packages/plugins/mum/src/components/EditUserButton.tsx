import { useMemo, useState } from 'react';
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
import { BuiltinRolesSelector } from './BuiltinRolesSelector';
import type { UserRow } from '../MumUserList';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';

const DEFAULT_DB = 'admin';

type RoleItem = string | { role: string; db: string };

const parseRoles = (roles: unknown): RoleItem[] => {
  if (!Array.isArray(roles)) return [];
  return roles
    .map((role) => {
      if (typeof role === 'string') return role;
      if (role && typeof role === 'object') {
        const r = role as Record<string, unknown>;
        if (r['role'] || r['name']) return { role: String(r['role'] ?? r['name']), db: String(r['db'] ?? '') };
      }
      return null;
    })
    .filter((r): r is RoleItem => r !== null);
};

interface EditUserButtonProps {
  row: UserRow;
  selectedTarget: string;
  builtinRoles: string[];
  rolesData?: RoleRow[];
  onSuccess?: (meta: { username: string; roles: unknown[]; db: string; target: string }) => void;
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
  const [roles, setRoles] = useState<RoleItem[]>([]);
  const [rolesDb, setRolesDb] = useState(DEFAULT_DB);

  const initialValues = useMemo(() => ({
    usernameValue: String(row?.['user'] ?? row?.['username'] ?? ''),
    rolesValue: parseRoles(row?.['roles']),
    dbValue: String(row?.['db'] ?? DEFAULT_DB),
  }), [row]);

  const openDialog = () => {
    setUsername(initialValues.usernameValue);
    setRoles(initialValues.rolesValue);
    setRolesDb(initialValues.dbValue);
    setPassword('');
    setError(null);
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
      const body: Record<string, unknown> = { target: selectedTarget, username, db: rolesDb || DEFAULT_DB, roles };
      if (password) body['password'] = password;
      await apiClient.post('/mum/ui/update-user', body);
      setOpen(false);
      onSuccess?.({ username, roles, db: rolesDb || DEFAULT_DB, target: selectedTarget });
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Failed to update user');
    } finally {
      setLoading(false);
    }
  };

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
            disabled={loading}
            helperText="Leave blank to keep existing password"
            fullWidth
          />
          <BuiltinRolesSelector
            builtinRoles={builtinRoles}
            customRoles={customRoles}
            value={roles}
            onChange={(v) => setRoles(v as RoleItem[])}
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
          <Button onClick={closeDialog} disabled={loading}>Cancel</Button>
          <Button onClick={handleSubmit} variant="contained" color="success" disabled={loading}>
            {loading ? 'Saving…' : 'Save'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
