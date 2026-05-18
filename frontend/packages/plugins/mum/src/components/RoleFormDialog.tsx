import { useState, useCallback, useEffect } from 'react';
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  IconButton,
  Radio,
  RadioGroup,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import type { RoleRef } from '../MumRoleList';

const DEFAULT_DB = 'admin';

const COLLECTION_ACTION_GROUPS: Record<string, string[]> = {
  'Query & Write': [
    'find', 'insert', 'update', 'remove',
    'bypassDocumentValidation', 'killCursors', 'killAnyCursor',
  ],
  'Collection & Index': [
    'createCollection', 'dropCollection', 'createIndex', 'dropIndex',
    'listIndexes', 'reIndex', 'convertToCapped', 'compact',
    'compactStructuredEncryptionData', 'collMod', 'renameCollectionSameDB',
  ],
  'Database Administration': [
    'dropDatabase', 'listCollections', 'dbStats', 'enableProfiler',
  ],
  'Plan Cache & Diagnostics': [
    'collStats', 'dbHash', 'validate', 'indexStats',
    'planCacheRead', 'planCacheWrite', 'planCacheIndexFilter', 'querySettings',
  ],
  'Change Streams': ['changeStream'],
  'Users & Roles': [
    'createUser', 'dropUser', 'viewUser',
    'changePassword', 'changeOwnPassword',
    'changeCustomData', 'changeOwnCustomData',
    'setAuthenticationRestriction',
    'grantRole', 'revokeRole',
    'createRole', 'dropRole', 'viewRole',
  ],
  'Sharding': [
    'enableSharding', 'analyzeShardKey', 'clearJumboFlag',
    'refineCollectionShardKey', 'moveChunk', 'reshardCollection',
    'checkMetadataConsistency',
  ],
  'Search Indexes (Atlas)': [
    'createSearchIndexes', 'dropSearchIndex', 'listSearchIndexes', 'updateSearchIndex',
  ],
};

const CLUSTER_ACTION_GROUPS: Record<string, string[]> = {
  'Server Administration': [
    'hostInfo', 'serverStatus', 'getCmdLineOpts', 'getLog',
    'getParameter', 'setParameter', 'getDefaultRWConcern', 'setDefaultRWConcern',
    'fsync', 'unlock', 'shutdown', 'logRotate', 'rotateCertificates',
    'connPoolStats', 'connPoolSync', 'dropConnections',
    'listDatabases', 'top', 'setFeatureCompatibilityVersion',
    'applicationMessage', 'bypassWriteBlockingMode', 'bypassDefaultMaxTimeMS',
    'setUserWriteBlockMode', 'forceUUID', 'oidReset',
  ],
  'Deployment Management': [
    'inprog', 'killop', 'invalidateUserCache', 'cpuProfiler',
    'useUUID', 'closeAllDatabases', 'touch',
    'authSchemaUpgrade', 'cleanupOrphaned',
  ],
  'Replication': [
    'appendOplogNote', 'replSetConfigure', 'replSetGetConfig',
    'replSetGetStatus', 'replSetHeartbeat', 'replSetStateChange', 'resync',
  ],
  'Sharding & Routing': [
    'addShard', 'removeShard', 'enableSharding',
    'flushRouterConfig', 'getClusterParameter', 'getShardMap', 'listShards',
    'moveCollection', 'shardedDataDistribution', 'shardingState', 'splitChunk',
    'transitionFromDedicatedConfigServer', 'transitionToDedicatedConfigServer',
    'unshardCollection', 'checkMetadataConsistency',
  ],
  'Sessions': ['listSessions', 'killAnySession', 'impersonate'],
};

const ACTION_GROUPS_BY_TYPE: Record<string, Record<string, string[]>> = {
  collection: COLLECTION_ACTION_GROUPS,
  cluster: CLUSTER_ACTION_GROUPS,
};

const allActionsForType = (resourceType: string): string[] =>
  Object.values(ACTION_GROUPS_BY_TYPE[resourceType] ?? COLLECTION_ACTION_GROUPS).flat();

export interface PrivilegeForm {
  resourceType: 'collection' | 'cluster';
  resourceDb: string;
  resourceCollection: string;
  actions: string[];
}

export const EMPTY_PRIVILEGE = (): PrivilegeForm => ({
  resourceType: 'collection',
  resourceDb: '',
  resourceCollection: '',
  actions: [],
});

interface MongoPrivilege {
  resource: { cluster?: boolean; db?: string; collection?: string };
  actions: string[];
}

const buildPrivileges = (privileges: PrivilegeForm[], effectiveDb: string): MongoPrivilege[] => {
  const isAdmin = effectiveDb === 'admin';
  return privileges.map((p) => ({
    resource:
      p.resourceType === 'cluster'
        ? { cluster: true }
        : { db: isAdmin ? p.resourceDb : effectiveDb, collection: p.resourceCollection },
    actions: p.actions,
  }));
};

interface PrivilegeEntryProps {
  priv: PrivilegeForm;
  index: number;
  onChange: (index: number, updated: PrivilegeForm) => void;
  onRemove: (index: number) => void;
  disabled: boolean;
  roleDb: string;
}

const PrivilegeEntry = ({ priv, index, onChange, onRemove, disabled, roleDb }: PrivilegeEntryProps) => {
  const isAdminRole = roleDb === 'admin';

  const toggleAction = (action: string) => {
    const next = priv.actions.includes(action)
      ? priv.actions.filter((a) => a !== action)
      : [...priv.actions, action];
    onChange(index, { ...priv, actions: next });
  };

  const set = (field: keyof PrivilegeForm) => (e: React.ChangeEvent<HTMLInputElement>) => {
    if (field === 'resourceType') {
      const newType = e.target.value as 'collection' | 'cluster';
      const validActions = allActionsForType(newType);
      onChange(index, { ...priv, resourceType: newType, actions: priv.actions.filter((a) => validActions.includes(a)) });
    } else {
      onChange(index, { ...priv, [field]: e.target.value });
    }
  };

  const actionGroups = ACTION_GROUPS_BY_TYPE[priv.resourceType] ?? COLLECTION_ACTION_GROUPS;

  const clusterRadio = (
    <FormControlLabel
      value="cluster"
      control={<Radio size="small" />}
      label="Cluster"
      disabled={disabled || !isAdminRole}
    />
  );

  return (
    <Box sx={{ border: (t) => `1px solid ${t.palette.divider}`, borderRadius: 1, p: 2, display: 'grid', gap: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center' }}>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1, fontWeight: 600 }}>
          Privilege #{index + 1}
        </Typography>
        <Tooltip title="Remove privilege">
          <span>
            <IconButton size="small" onClick={() => onRemove(index)} disabled={disabled}>✕</IconButton>
          </span>
        </Tooltip>
      </Box>

      <FormControl component="fieldset" disabled={disabled}>
        <FormLabel sx={{ fontSize: '0.75rem', mb: 0.5 }}>Resource type</FormLabel>
        <RadioGroup row value={priv.resourceType} onChange={set('resourceType')}>
          <FormControlLabel value="collection" control={<Radio size="small" />} label="Database and Collection" disabled={disabled} />
          {isAdminRole ? clusterRadio : (
            <Tooltip title="Cluster resources are only available for roles owned by the 'admin' database">
              <span>{clusterRadio}</span>
            </Tooltip>
          )}
        </RadioGroup>
      </FormControl>

      {priv.resourceType === 'collection' && (
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField
            label="Database"
            placeholder={isAdminRole ? 'empty = all databases' : undefined}
            size="small"
            value={isAdminRole ? priv.resourceDb : roleDb}
            onChange={isAdminRole ? set('resourceDb') : undefined}
            disabled={disabled || !isAdminRole}
            helperText={!isAdminRole ? `Locked to role's database "${roleDb}"` : undefined}
            fullWidth
          />
          <TextField
            label="Collection"
            placeholder="empty = all collections"
            size="small"
            value={priv.resourceCollection}
            onChange={set('resourceCollection')}
            disabled={disabled}
            fullWidth
          />
        </Box>
      )}

      <Typography variant="caption" color="text.secondary">
        {priv.resourceType === 'cluster'
          ? 'Cluster-level actions affect the entire system (replication, sharding, server config).'
          : isAdminRole
            ? 'Leave both fields empty to match all non-system collections across all databases.'
            : `Database is locked to "${roleDb}". Leave Collection empty to match all collections in that database.`}
      </Typography>

      <FormControl component="fieldset" fullWidth disabled={disabled}>
        <FormLabel sx={{ fontSize: '0.75rem', mb: 0.5 }}>Actions</FormLabel>
        <Box sx={{ border: (t) => `1px solid ${t.palette.divider}`, borderRadius: 1, maxHeight: 260, overflowY: 'auto', p: 1 }}>
          {Object.entries(actionGroups).map(([group, actions]) => (
            <Box key={group} sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>{group}</Typography>
              <FormGroup sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', columnGap: 0.5 }}>
                {actions.map((action) => (
                  <FormControlLabel
                    key={action}
                    control={
                      <Checkbox
                        size="small"
                        checked={priv.actions.includes(action)}
                        onChange={() => toggleAction(action)}
                        disabled={disabled}
                      />
                    }
                    label={<Typography variant="caption">{action}</Typography>}
                  />
                ))}
              </FormGroup>
              <Divider sx={{ mt: 0.5 }} />
            </Box>
          ))}
        </Box>
      </FormControl>

      {priv.actions.length > 0 && (
        <Box>
          <Typography variant="caption" color="text.secondary">
            {priv.actions.length} action{priv.actions.length !== 1 ? 's' : ''} selected
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
            {priv.actions.map((a) => (
              <Chip key={a} label={a} size="small" onDelete={disabled ? undefined : () => toggleAction(a)} />
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
};

interface InheritedRolesSelectorProps {
  rolesData: Array<{ role?: string; db?: string; isBuiltin?: boolean }>;
  value: RoleRef[];
  onChange: (val: RoleRef[]) => void;
  disabled: boolean;
  excludeKey?: string | null;
  roleDb?: string;
}

const InheritedRolesSelector = ({ rolesData, value, onChange, disabled, excludeKey = null, roleDb = 'admin' }: InheritedRolesSelectorProps) => {
  const isAdmin = roleDb === 'admin';
  const customRoles = rolesData.filter(
    (r) => !r.isBuiltin && r.role && `${r.role}@${r.db}` !== excludeKey && (isAdmin || r.db === roleDb),
  );
  const selectedKeys = value.map((r) => `${r.role}@${r.db}`);

  const toggle = (r: { role?: string; db?: string }) => {
    const key = `${r.role}@${r.db}`;
    if (selectedKeys.includes(key)) {
      onChange(value.filter((v) => `${v.role}@${v.db}` !== key));
    } else {
      onChange([...value, { role: r.role!, db: r.db! }]);
    }
  };

  return (
    <FormControl component="fieldset" fullWidth disabled={disabled}>
      <FormLabel sx={{ mb: 0.5 }}>
        Inherited roles (custom{!isAdmin ? ` — scoped to "${roleDb}"` : ''})
      </FormLabel>
      {customRoles.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          {isAdmin
            ? 'No custom roles available to inherit from.'
            : `No custom roles in the "${roleDb}" database to inherit from.`}
        </Typography>
      ) : (
        <Box sx={{ border: (t) => `1px solid ${t.palette.divider}`, borderRadius: 1, maxHeight: 160, overflowY: 'auto', p: 1 }}>
          <FormGroup sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', columnGap: 1 }}>
            {customRoles.map((r) => {
              const key = `${r.role}@${r.db}`;
              return (
                <FormControlLabel
                  key={key}
                  control={
                    <Checkbox
                      size="small"
                      checked={selectedKeys.includes(key)}
                      onChange={() => toggle(r)}
                      disabled={disabled}
                    />
                  }
                  label={
                    <Typography variant="caption">
                      {r.role}
                      {r.db ? <Typography component="span" variant="caption" color="text.secondary"> @ {r.db}</Typography> : null}
                    </Typography>
                  }
                />
              );
            })}
          </FormGroup>
        </Box>
      )}
      {value.length > 0 && (
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
          {value.map((r) => (
            <Chip
              key={`${r.role}@${r.db}`}
              label={`${r.role} @ ${r.db}`}
              size="small"
              onDelete={disabled ? undefined : () => toggle(r)}
            />
          ))}
        </Box>
      )}
    </FormControl>
  );
};

export interface RoleFormValues {
  role: string;
  db: string;
  privileges: PrivilegeForm[];
  inheritedRoles: RoleRef[];
}

interface RoleFormDialogProps {
  open: boolean;
  onClose: () => void;
  onSubmit: (values: { role: string; db: string; privileges: MongoPrivilege[]; inheritedRoles: RoleRef[] }) => Promise<void>;
  initialValues?: RoleFormValues | null;
  rolesData?: Array<{ role?: string; db?: string; isBuiltin?: boolean }>;
  title: string;
  submitLabel: string;
  editMode?: boolean;
}

export function RoleFormDialog({
  open,
  onClose,
  onSubmit,
  initialValues = null,
  rolesData = [],
  title,
  submitLabel,
  editMode = false,
}: RoleFormDialogProps) {
  const [roleName, setRoleName] = useState('');
  const [db, setDb] = useState(DEFAULT_DB);
  const [privileges, setPrivileges] = useState<PrivilegeForm[]>([]);
  const [inheritedRoles, setInheritedRoles] = useState<RoleRef[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (initialValues) {
      setRoleName(initialValues.role ?? '');
      setDb(initialValues.db ?? DEFAULT_DB);
      setPrivileges(initialValues.privileges ?? []);
      setInheritedRoles(initialValues.inheritedRoles ?? []);
    } else {
      setRoleName('');
      setDb(DEFAULT_DB);
      setPrivileges([]);
      setInheritedRoles([]);
    }
    setError(null);
    setLoading(false);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleClose = () => { if (!loading) onClose(); };

  const handlePrivilegeChange = useCallback((index: number, updated: PrivilegeForm) => {
    setPrivileges((prev) => prev.map((p, i) => (i === index ? updated : p)));
  }, []);

  const handlePrivilegeRemove = useCallback((index: number) => {
    setPrivileges((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleAddPrivilege = () => setPrivileges((prev) => [...prev, EMPTY_PRIVILEGE()]);

  const handleSubmit = async () => {
    if (!roleName.trim()) { setError('Role name is required.'); return; }
    const effectiveDb = db || DEFAULT_DB;
    if (effectiveDb !== 'admin' && privileges.some((p) => p.resourceType === 'cluster')) {
      setError("Cluster resources are only allowed for roles owned by the 'admin' database.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await onSubmit({
        role: roleName.trim(),
        db: effectiveDb,
        privileges: buildPrivileges(privileges, effectiveDb),
        inheritedRoles,
      });
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string };
      setError(err?.response?.data?.detail ?? err?.message ?? 'Operation failed');
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md" scroll="paper" disableScrollLock>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent dividers sx={{ display: 'grid', gap: 2.5 }}>
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField
            label="Role name"
            value={roleName}
            onChange={(e) => setRoleName(e.target.value)}
            disabled={loading || editMode}
            helperText={editMode ? 'Role name cannot be changed' : undefined}
            required
            fullWidth
          />
          <TextField
            label="Database"
            value={db}
            onChange={(e) => setDb(e.target.value)}
            disabled={loading || editMode}
            helperText={editMode ? 'Database cannot be changed' : 'Database that owns this role'}
            fullWidth
          />
        </Box>

        <InheritedRolesSelector
          rolesData={rolesData}
          value={inheritedRoles}
          onChange={setInheritedRoles}
          disabled={loading}
          excludeKey={editMode ? `${roleName}@${db || DEFAULT_DB}` : null}
          roleDb={db || DEFAULT_DB}
        />

        <FormControl component="fieldset" fullWidth>
          <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
            <FormLabel sx={{ flex: 1 }}>Privileges</FormLabel>
            <Button size="small" variant="outlined" onClick={handleAddPrivilege} disabled={loading}>
              + add privilege
            </Button>
          </Box>
          {privileges.length === 0 ? (
            <Typography variant="body2" color="text.secondary">
              No privileges defined. A role with no privileges can still inherit from other roles.
            </Typography>
          ) : (
            <Box sx={{ display: 'grid', gap: 2 }}>
              {privileges.map((priv, i) => (
                <PrivilegeEntry
                  key={i}
                  priv={priv}
                  index={i}
                  onChange={handlePrivilegeChange}
                  onRemove={handlePrivilegeRemove}
                  disabled={loading}
                  roleDb={db || DEFAULT_DB}
                />
              ))}
            </Box>
          )}
        </FormControl>

        {error && <Typography color="error" variant="body2">{error}</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={loading}>Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" color="success" disabled={loading}>
          {loading ? `${submitLabel}…` : submitLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
