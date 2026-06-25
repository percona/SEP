import { useMemo, useState } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  TextField,
  Typography,
} from '@mui/material';

export interface RoleEntry {
  role: string;
  db: string;
}

/**
 * MongoDB built-in roles that are only valid on the "admin" database.
 * Cluster-level, backup/restore, and any-database roles all live in admin.
 */
const ADMIN_ONLY_BUILTIN_ROLES = new Set([
  'clusterAdmin', 'clusterManager', 'clusterMonitor', 'hostManager',
  'backup', 'restore',
  'readAnyDatabase', 'readWriteAnyDatabase', 'dbAdminAnyDatabase', 'userAdminAnyDatabase',
  'root', '__system',
]);

interface UserRolesEditorProps {
  builtinRoles?: string[];
  customRoles?: RoleEntry[];
  value?: RoleEntry[];
  onChange?: (val: RoleEntry[]) => void;
  /** Default db applied when a built-in role checkbox is ticked. */
  defaultDb?: string;
  disabled?: boolean;
}

export function UserRolesEditor({
  builtinRoles = [],
  customRoles = [],
  value = [],
  onChange,
  defaultDb = 'admin',
  disabled = false,
}: UserRolesEditorProps) {
  const [search, setSearch] = useState('');
  const lower = search.trim().toLowerCase();

  const filteredBuiltin = useMemo(
    () => (lower ? builtinRoles.filter((r) => r.toLowerCase().includes(lower)) : builtinRoles),
    [builtinRoles, lower],
  );

  const filteredCustom = useMemo(
    () =>
      lower
        ? customRoles.filter(
            (r) => r.role.toLowerCase().includes(lower) || r.db.toLowerCase().includes(lower),
          )
        : customRoles,
    [customRoles, lower],
  );

  // A builtin is "checked" if value contains any entry with that role name (db is irrelevant).
  const builtinCheckedSet = useMemo(
    () => new Set(value.filter((v) => builtinRoles.includes(v.role)).map((v) => v.role)),
    [value, builtinRoles],
  );

  // A custom role is "checked" if value contains an exact role+db match.
  const customCheckedSet = useMemo(
    () =>
      new Set(
        value
          .filter((v) => !builtinRoles.includes(v.role))
          .map((v) => `${v.role}\0${v.db}`),
      ),
    [value, builtinRoles],
  );

  const toggleBuiltin = (role: string) => {
    if (builtinCheckedSet.has(role)) {
      // Remove all entries for this role regardless of db.
      onChange?.(value.filter((v) => v.role !== role));
    } else {
      // Admin-only roles are always pinned to the "admin" database.
      const db = ADMIN_ONLY_BUILTIN_ROLES.has(role) ? 'admin' : defaultDb;
      onChange?.([...value, { role, db }]);
    }
  };

  const toggleCustom = (r: RoleEntry) => {
    const key = `${r.role}\0${r.db}`;
    if (customCheckedSet.has(key)) {
      onChange?.(value.filter((v) => !(v.role === r.role && v.db === r.db)));
    } else {
      onChange?.([...value, { role: r.role, db: r.db }]);
    }
  };

  const updateEntryDb = (idx: number, db: string) => {
    onChange?.(value.map((v, i) => (i === idx ? { ...v, db } : v)));
  };

  const removeEntry = (idx: number) => {
    onChange?.(value.filter((_, i) => i !== idx));
  };

  /** Insert a copy of the row immediately after it so the user can set a different db. */
  const addSameRoleOtherDb = (idx: number) => {
    const next = [...value];
    next.splice(idx + 1, 0, { ...value[idx], db: '' });
    onChange?.(next);
  };

  return (
    <FormControl component="fieldset" fullWidth>
      <FormLabel sx={{ mb: 1 }}>Roles</FormLabel>

      {/* ── picker ─────────────────────────────────────── */}
      <TextField
        label="Search roles"
        placeholder="Filter built-in and custom roles…"
        size="small"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        disabled={disabled}
      />
      <Box
        sx={{
          mt: 1,
          border: (t) => `1px solid ${t.palette.divider}`,
          borderRadius: 1,
          maxHeight: 220,
          overflowY: 'auto',
          p: 1,
        }}
      >
        {filteredBuiltin.length > 0 && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Built-in
            </Typography>
            <FormGroup
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', sm: 'repeat(2,1fr)', md: 'repeat(3,1fr)' },
                columnGap: 1,
                rowGap: 0.25,
              }}
            >
              {filteredBuiltin.map((role) => (
                <FormControlLabel
                  key={role}
                  control={
                    <Checkbox
                      checked={builtinCheckedSet.has(role)}
                      onChange={() => toggleBuiltin(role)}
                      disabled={disabled}
                      size="small"
                    />
                  }
                  label={role}
                  disabled={disabled}
                />
              ))}
            </FormGroup>
          </>
        )}

        {filteredCustom.length > 0 && (
          <>
            {filteredBuiltin.length > 0 && <Divider sx={{ my: 1 }} />}
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Custom
            </Typography>
            <FormGroup
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', sm: 'repeat(2,1fr)', md: 'repeat(3,1fr)' },
                columnGap: 1,
                rowGap: 0.25,
              }}
            >
              {filteredCustom.map((r) => {
                const key = `${r.role}\0${r.db}`;
                return (
                  <FormControlLabel
                    key={key}
                    control={
                      <Checkbox
                        checked={customCheckedSet.has(key)}
                        onChange={() => toggleCustom(r)}
                        disabled={disabled}
                        size="small"
                      />
                    }
                    label={
                      <Typography variant="body2">
                        {r.role}
                        {r.db && (
                          <Typography component="span" variant="caption" color="text.secondary">
                            {' '}@ {r.db}
                          </Typography>
                        )}
                      </Typography>
                    }
                    disabled={disabled}
                  />
                );
              })}
            </FormGroup>
          </>
        )}

        {filteredBuiltin.length === 0 && filteredCustom.length === 0 && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 1 }}>
            {builtinRoles.length + customRoles.length > 0
              ? `No roles match "${search}".`
              : 'No roles available.'}
          </Typography>
        )}
      </Box>

      {/* ── selected roles with per-role db ───────────── */}
      {value.length > 0 ? (
        <Box sx={{ mt: 1.5 }}>
          <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
            Selected — set database per role
          </Typography>
          <Box
            sx={{
              mt: 0.5,
              border: (t) => `1px solid ${t.palette.divider}`,
              borderRadius: 1,
              overflow: 'hidden',
            }}
          >
            {value.map((entry, idx) => {
              const adminOnly = ADMIN_ONLY_BUILTIN_ROLES.has(entry.role);
              return (
              <Box
                key={idx}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 1,
                  px: 1.5,
                  py: 0.75,
                  borderBottom: (t) =>
                    idx < value.length - 1 ? `1px solid ${t.palette.divider}` : 'none',
                  bgcolor: idx % 2 !== 0 ? 'action.hover' : 'transparent',
                }}
              >
                <Typography variant="body2" sx={{ flex: 1, fontWeight: 500 }}>
                  {entry.role}
                </Typography>
                <TextField
                  size="small"
                  label="db"
                  value={entry.db}
                  onChange={(e) => updateEntryDb(idx, e.target.value)}
                  disabled={disabled || adminOnly}
                  title={adminOnly ? 'This role is only valid on the admin database' : undefined}
                  sx={{ width: 150 }}
                />
                {!adminOnly && (
                  <Button
                    size="small"
                    variant="text"
                    title="Add same role on a different database"
                    onClick={() => addSameRoleOtherDb(idx)}
                    disabled={disabled}
                    sx={{ minWidth: 28, px: 0.5, fontSize: '1.1rem', lineHeight: 1 }}
                  >
                    +
                  </Button>
                )}
                <Button
                  size="small"
                  variant="text"
                  color="error"
                  onClick={() => removeEntry(idx)}
                  disabled={disabled}
                  sx={{ minWidth: 28, px: 0.5, fontSize: '1.1rem', lineHeight: 1 }}
                >
                  ×
                </Button>
              </Box>
              );
            })}
          </Box>
        </Box>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          No roles selected.
        </Typography>
      )}

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', mt: 0.5 }}>
        <Button
          size="small"
          color="secondary"
          onClick={() => onChange?.([])}
          disabled={disabled || value.length === 0}
        >
          Clear all
        </Button>
      </Box>
    </FormControl>
  );
}
