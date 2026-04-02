import React, { useState, useCallback, useEffect } from "react";
import apiClient from "../../../ui/apiClient";
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
} from "@mui/material";

const DEFAULT_DB = "admin";

// ─── MongoDB action catalogue ────────────────────────────────────────────────
// Collection/database-level actions — apply to {db, collection} resources.
const COLLECTION_ACTION_GROUPS = {
  "Query & Write": [
    "find", "insert", "update", "remove",
    "bypassDocumentValidation", "killCursors", "killAnyCursor",
  ],
  "Collection & Index": [
    "createCollection", "dropCollection", "createIndex", "dropIndex",
    "listIndexes", "reIndex", "convertToCapped", "compact",
    "compactStructuredEncryptionData", "collMod", "renameCollectionSameDB",
  ],
  "Database Administration": [
    "dropDatabase", "listCollections", "dbStats", "enableProfiler",
  ],
  "Plan Cache & Diagnostics": [
    "collStats", "dbHash", "validate", "indexStats",
    "planCacheRead", "planCacheWrite", "planCacheIndexFilter", "querySettings",
  ],
  "Change Streams": [
    "changeStream",
  ],
  "Users & Roles": [
    "createUser", "dropUser", "viewUser",
    "changePassword", "changeOwnPassword",
    "changeCustomData", "changeOwnCustomData",
    "setAuthenticationRestriction",
    "grantRole", "revokeRole",
    "createRole", "dropRole", "viewRole",
  ],
  "Sharding": [
    "enableSharding", "analyzeShardKey", "clearJumboFlag",
    "refineCollectionShardKey", "moveChunk", "reshardCollection",
    "checkMetadataConsistency",
  ],
  "Search Indexes (Atlas)": [
    "createSearchIndexes", "dropSearchIndex", "listSearchIndexes", "updateSearchIndex",
  ],
};

// Cluster-level actions — only valid on {cluster: true} resources.
const CLUSTER_ACTION_GROUPS = {
  "Server Administration": [
    "hostInfo", "serverStatus", "getCmdLineOpts", "getLog",
    "getParameter", "setParameter", "getDefaultRWConcern", "setDefaultRWConcern",
    "fsync", "unlock", "shutdown", "logRotate", "rotateCertificates",
    "connPoolStats", "connPoolSync", "dropConnections",
    "listDatabases", "top", "setFeatureCompatibilityVersion",
    "applicationMessage", "bypassWriteBlockingMode", "bypassDefaultMaxTimeMS",
    "setUserWriteBlockMode", "forceUUID", "oidReset",
  ],
  "Deployment Management": [
    "inprog", "killop", "invalidateUserCache", "cpuProfiler",
    "useUUID", "closeAllDatabases", "touch",
    "authSchemaUpgrade", "cleanupOrphaned",
  ],
  "Replication": [
    "appendOplogNote", "replSetConfigure", "replSetGetConfig",
    "replSetGetStatus", "replSetHeartbeat", "replSetStateChange", "resync",
  ],
  "Sharding & Routing": [
    "addShard", "removeShard", "enableSharding",
    "flushRouterConfig", "getClusterParameter", "getShardMap", "listShards",
    "moveCollection", "shardedDataDistribution", "shardingState", "splitChunk",
    "transitionFromDedicatedConfigServer", "transitionToDedicatedConfigServer",
    "unshardCollection", "checkMetadataConsistency",
  ],
  "Sessions": [
    "listSessions", "killAnySession", "impersonate",
  ],
};

const ACTION_GROUPS_BY_TYPE = {
  collection: COLLECTION_ACTION_GROUPS,
  cluster: CLUSTER_ACTION_GROUPS,
};

const allActionsForType = (resourceType) =>
  Object.values(ACTION_GROUPS_BY_TYPE[resourceType] || COLLECTION_ACTION_GROUPS).flat();

// ─── Privilege entry ──────────────────────────────────────────────────────────
const EMPTY_PRIVILEGE = () => ({
  resourceType: "collection",
  resourceDb: "",
  resourceCollection: "",
  actions: [],
});

const buildResource = (priv) => {
  if (priv.resourceType === "cluster") return { cluster: true };
  return { db: priv.resourceDb, collection: priv.resourceCollection };
};

const PrivilegeEntry = ({ priv, index, onChange, onRemove, disabled, roleDb }) => {
  const isAdminRole = roleDb === "admin";

  const toggleAction = (action) => {
    const next = priv.actions.includes(action)
      ? priv.actions.filter((a) => a !== action)
      : [...priv.actions, action];
    onChange(index, { ...priv, actions: next });
  };

  const set = (field) => (e) => {
    if (field === "resourceType") {
      const newType = e.target.value;
      const validActions = allActionsForType(newType);
      const filteredActions = priv.actions.filter((a) => validActions.includes(a));
      // When switching to collection on a non-admin role, lock db to roleDb.
      const resourceDb = newType === "collection" && !isAdminRole ? roleDb : priv.resourceDb;
      onChange(index, { ...priv, resourceType: newType, actions: filteredActions, resourceDb });
    } else {
      onChange(index, { ...priv, [field]: e.target.value });
    }
  };

  const actionGroups = ACTION_GROUPS_BY_TYPE[priv.resourceType] || COLLECTION_ACTION_GROUPS;

  const clusterRadio = (
    <FormControlLabel
      value="cluster"
      control={<Radio size="small" />}
      label="Cluster"
      disabled={disabled || !isAdminRole}
    />
  );

  return (
    <Box
      sx={{
        border: (t) => `1px solid ${t.palette.divider}`,
        borderRadius: 1,
        p: 2,
        display: "grid",
        gap: 1.5,
      }}
    >
      {/* Header */}
      <Box sx={{ display: "flex", alignItems: "center" }}>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1, fontWeight: 600 }}>
          Privilege #{index + 1}
        </Typography>
        <Tooltip title="Remove privilege">
          <span>
            <IconButton size="small" onClick={() => onRemove(index)} disabled={disabled}>
              ✕
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {/* Resource type */}
      <FormControl component="fieldset" disabled={disabled}>
        <FormLabel sx={{ fontSize: "0.75rem", mb: 0.5 }}>Resource type</FormLabel>
        <RadioGroup row value={priv.resourceType} onChange={set("resourceType")}>
          <FormControlLabel value="collection" control={<Radio size="small" />} label="Collection / Database" disabled={disabled} />
          {isAdminRole ? (
            clusterRadio
          ) : (
            <Tooltip title="Cluster resources are only available for roles owned by the 'admin' database">
              <span>{clusterRadio}</span>
            </Tooltip>
          )}
        </RadioGroup>
      </FormControl>

      {/* Collection: database + collection fields in a row */}
      {priv.resourceType === "collection" && (
        <Box sx={{ display: "flex", gap: 2 }}>
          <TextField
            label="Database"
            placeholder={isAdminRole ? "empty = all databases" : undefined}
            size="small"
            value={priv.resourceDb}
            onChange={set("resourceDb")}
            disabled={disabled || !isAdminRole}
            helperText={!isAdminRole ? `Locked to role's database "${roleDb}"` : undefined}
            fullWidth
          />
          <TextField
            label="Collection"
            placeholder="empty = all collections"
            size="small"
            value={priv.resourceCollection}
            onChange={set("resourceCollection")}
            disabled={disabled}
            fullWidth
          />
        </Box>
      )}

      <Typography variant="caption" color="text.secondary">
        {priv.resourceType === "cluster"
          ? "Cluster-level actions affect the entire system (replication, sharding, server config)."
          : isAdminRole
            ? "Leave both fields empty to match all non-system collections across all databases."
            : `Database is locked to "${roleDb}". Leave Collection empty to match all collections in that database.`}
      </Typography>

      {/* Actions */}
      <FormControl component="fieldset" fullWidth disabled={disabled}>
        <FormLabel sx={{ fontSize: "0.75rem", mb: 0.5 }}>Actions</FormLabel>
        <Box
          sx={{
            border: (t) => `1px solid ${t.palette.divider}`,
            borderRadius: 1,
            maxHeight: 260,
            overflowY: "auto",
            p: 1,
          }}
        >
          {Object.entries(actionGroups).map(([group, actions]) => (
            <Box key={group} sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                {group}
              </Typography>
              <FormGroup
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                  columnGap: 0.5,
                }}
              >
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

      {/* Selected actions chips */}
      {priv.actions.length > 0 && (
        <Box>
          <Typography variant="caption" color="text.secondary">
            {priv.actions.length} action{priv.actions.length !== 1 ? "s" : ""} selected
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
            {priv.actions.map((a) => (
              <Chip
                key={a}
                label={a}
                size="small"
                onDelete={disabled ? undefined : () => toggleAction(a)}
              />
            ))}
          </Box>
        </Box>
      )}
    </Box>
  );
};

// ─── Inherited roles selector ─────────────────────────────────────────────────
const InheritedRolesSelector = ({ rolesData, value, onChange, disabled }) => {
  const customRoles = rolesData.filter((r) => !r.isBuiltin && r.role);
  const selectedKeys = value.map((r) => `${r.role}@${r.db}`);

  const toggle = (r) => {
    const key = `${r.role}@${r.db}`;
    if (selectedKeys.includes(key)) {
      onChange(value.filter((v) => `${v.role}@${v.db}` !== key));
    } else {
      onChange([...value, { role: r.role, db: r.db }]);
    }
  };

  return (
    <FormControl component="fieldset" fullWidth disabled={disabled}>
      <FormLabel sx={{ mb: 0.5 }}>Inherited roles (custom)</FormLabel>
      {customRoles.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No custom roles available to inherit from.
        </Typography>
      ) : (
        <Box
          sx={{
            border: (t) => `1px solid ${t.palette.divider}`,
            borderRadius: 1,
            maxHeight: 160,
            overflowY: "auto",
            p: 1,
          }}
        >
          <FormGroup
            sx={{
              display: "grid",
              gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
              columnGap: 1,
            }}
          >
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
                      {r.db ? (
                        <Typography component="span" variant="caption" color="text.secondary">
                          {" "}@ {r.db}
                        </Typography>
                      ) : null}
                    </Typography>
                  }
                />
              );
            })}
          </FormGroup>
        </Box>
      )}
      {value.length > 0 && (
        <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
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

// ─── Main component ───────────────────────────────────────────────────────────
const AddCustomRoleButton = ({
  selectedTarget,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [roleName, setRoleName] = useState("");
  const [db, setDb] = useState(DEFAULT_DB);
  const [privileges, setPrivileges] = useState([]);
  const [inheritedRoles, setInheritedRoles] = useState([]);

  const resetForm = () => {
    setRoleName("");
    setDb(DEFAULT_DB);
    setPrivileges([]);
    setInheritedRoles([]);
    setError(null);
  };

  const handleOpen = () => { resetForm(); setOpen(true); };
  const handleClose = () => { if (!loading) setOpen(false); };

  // When the role's owning DB changes away from 'admin', sanitize existing privileges:
  // - force any cluster resource type to collection
  // - lock resourceDb to the new db value
  useEffect(() => {
    if (db === "admin") return;
    setPrivileges((prev) =>
      prev.map((p) => {
        const base =
          p.resourceType === "cluster"
            ? {
                ...p,
                resourceType: "collection",
                actions: p.actions.filter((a) =>
                  allActionsForType("collection").includes(a)
                ),
              }
            : p;
        return base.resourceDb !== db ? { ...base, resourceDb: db } : base;
      })
    );
  }, [db]);

  const handlePrivilegeChange = useCallback((index, updated) => {
    setPrivileges((prev) => prev.map((p, i) => (i === index ? updated : p)));
  }, []);

  const handlePrivilegeRemove = useCallback((index) => {
    setPrivileges((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleAddPrivilege = () =>
    setPrivileges((prev) => [
      ...prev,
      { ...EMPTY_PRIVILEGE(), resourceDb: db === "admin" ? "" : db },
    ]);

  const handleSubmit = async () => {
    if (!selectedTarget) { setError("Select an executor host first."); return; }
    if (!roleName.trim()) { setError("Role name is required."); return; }

    const builtPrivileges = privileges.map((p) => ({
      resource: buildResource(p),
      actions: p.actions,
    }));

    setLoading(true);
    setError(null);
    try {
      await apiClient.post("/mum/ui/create-role", {
        target: selectedTarget,
        role: roleName.trim(),
        db: db || DEFAULT_DB,
        privileges: builtPrivileges,
        inheritedRoles,
      });
      setOpen(false);
      onSuccess?.({ role: roleName.trim(), db: db || DEFAULT_DB, target: selectedTarget });
      resetForm();
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Failed to create role");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button variant="contained" color="success" onClick={handleOpen} {...buttonProps}>
        + add custom role
      </Button>

      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md" scroll="paper" disableScrollLock>
        <DialogTitle>Create custom MongoDB role</DialogTitle>
        <DialogContent dividers sx={{ display: "grid", gap: 2.5 }}>
          {/* Basic info */}
          <Box sx={{ display: "flex", gap: 2 }}>
            <TextField
              label="Role name"
              value={roleName}
              onChange={(e) => setRoleName(e.target.value)}
              disabled={loading}
              required
              fullWidth
            />
            <TextField
              label="Database"
              value={db}
              onChange={(e) => setDb(e.target.value)}
              disabled={loading}
              helperText="Database that owns this role"
              fullWidth
            />
          </Box>

          {/* Inherited roles */}
          <InheritedRolesSelector
            rolesData={rolesData}
            value={inheritedRoles}
            onChange={setInheritedRoles}
            disabled={loading}
          />

          {/* Privileges */}
          <FormControl component="fieldset" fullWidth>
            <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
              <FormLabel sx={{ flex: 1 }}>Privileges</FormLabel>
              <Button
                size="small"
                variant="outlined"
                onClick={handleAddPrivilege}
                disabled={loading}
              >
                + add privilege
              </Button>
            </Box>
            {privileges.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No privileges defined. A role with no privileges can still inherit from other roles.
              </Typography>
            ) : (
              <Box sx={{ display: "grid", gap: 2 }}>
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

          {error && (
            <Typography color="error" variant="body2">
              {error}
            </Typography>
          )}
        </DialogContent>

        <DialogActions>
          <Button onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            variant="contained"
            color="success"
            disabled={loading}
          >
            {loading ? "Creating…" : "Create role"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default AddCustomRoleButton;
