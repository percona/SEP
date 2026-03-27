import React, { useState, useCallback } from "react";
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
  MenuItem,
  Select,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";

const DEFAULT_DB = "admin";

// ─── MongoDB action catalogue ────────────────────────────────────────────────
const ACTION_GROUPS = {
  "Query & Write": [
    "find", "insert", "update", "remove", "aggregate",
    "bypassDocumentValidation",
  ],
  "Collection": [
    "createCollection", "dropCollection", "createIndex", "dropIndex",
    "listIndexes", "collStats", "compact", "convertToCapped",
    "emptycapped", "reIndex", "validate",
  ],
  "Database": [
    "dropDatabase", "listCollections", "dbStats", "dbHash",
    "planCacheRead", "planCacheWrite", "planCacheIndexFilter",
  ],
  "Users & Roles": [
    "createUser", "dropUser", "grantRolesToUser", "revokeRolesFromUser",
    "viewUser", "changeOwnPassword", "changeAnyPassword",
    "changeOwnCustomData", "changeAnyCustomData",
    "createRole", "dropRole", "grantRolesToRole", "revokeRolesFromRole",
    "viewRole",
  ],
  "Cluster": [
    "hostInfo", "listDatabases", "serverStatus", "top", "killOp",
    "killCursors", "connPoolStats", "getCmdLineOpts", "getLog",
    "getParameter", "setParameter", "shutdown", "fsync",
    "addShard", "removeShard", "enableSharding",
  ],
  "Replication": [
    "appendOplogNote", "replSetConfigure", "replSetGetConfig",
    "replSetGetStatus", "replSetHeartbeat", "replSetStateChange", "resync",
  ],
};

// ─── Privilege entry ──────────────────────────────────────────────────────────
const EMPTY_PRIVILEGE = () => ({
  resourceType: "collection",
  resourceDb: "",
  resourceCollection: "",
  actions: [],
});

const buildResource = (priv) => {
  if (priv.resourceType === "cluster") return { cluster: true };
  if (priv.resourceType === "anyResource") return { anyResource: true };
  return { db: priv.resourceDb, collection: priv.resourceCollection };
};

const PrivilegeEntry = ({ priv, index, onChange, onRemove, disabled }) => {
  const toggleAction = (action) => {
    const next = priv.actions.includes(action)
      ? priv.actions.filter((a) => a !== action)
      : [...priv.actions, action];
    onChange(index, { ...priv, actions: next });
  };

  const set = (field) => (e) =>
    onChange(index, { ...priv, [field]: e.target.value });

  return (
    <Box
      sx={{
        border: (t) => `1px solid ${t.palette.divider}`,
        borderRadius: 1,
        p: 1.5,
        display: "grid",
        gap: 1,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Typography variant="caption" color="text.secondary" sx={{ flex: 1 }}>
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
      <FormControl size="small" fullWidth disabled={disabled}>
        <FormLabel sx={{ mb: 0.5, fontSize: "0.75rem" }}>Resource type</FormLabel>
        <Select value={priv.resourceType} onChange={set("resourceType")} size="small">
          <MenuItem value="collection">Collection (db + collection)</MenuItem>
          <MenuItem value="cluster">Cluster</MenuItem>
          <MenuItem value="anyResource">Any resource</MenuItem>
        </Select>
      </FormControl>

      {priv.resourceType === "collection" && (
        <Box sx={{ display: "flex", gap: 1 }}>
          <TextField
            label="Database"
            placeholder="empty = any"
            size="small"
            value={priv.resourceDb}
            onChange={set("resourceDb")}
            disabled={disabled}
            fullWidth
          />
          <TextField
            label="Collection"
            placeholder="empty = any"
            size="small"
            value={priv.resourceCollection}
            onChange={set("resourceCollection")}
            disabled={disabled}
            fullWidth
          />
        </Box>
      )}

      {/* Actions */}
      <FormControl component="fieldset" fullWidth disabled={disabled}>
        <FormLabel sx={{ fontSize: "0.75rem", mb: 0.5 }}>Actions</FormLabel>
        <Box
          sx={{
            border: (t) => `1px solid ${t.palette.divider}`,
            borderRadius: 1,
            maxHeight: 220,
            overflowY: "auto",
            p: 1,
          }}
        >
          {Object.entries(ACTION_GROUPS).map(([group, actions]) => (
            <Box key={group} sx={{ mb: 1 }}>
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
                {group}
              </Typography>
              <FormGroup
                sx={{
                  display: "grid",
                  gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
                  columnGap: 1,
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
        {priv.actions.length > 0 && (
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
        )}
      </FormControl>
    </Box>
  );
};

// ─── Inherited roles selector ─────────────────────────────────────────────────
// Shows custom roles from rolesData as checkboxes; role identity = role@db
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
              gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
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
                      {r.db ? <> <span style={{ opacity: 0.6 }}>@ {r.db}</span></> : null}
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

  const handlePrivilegeChange = useCallback((index, updated) => {
    setPrivileges((prev) => prev.map((p, i) => (i === index ? updated : p)));
  }, []);

  const handlePrivilegeRemove = useCallback((index) => {
    setPrivileges((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleAddPrivilege = () => setPrivileges((prev) => [...prev, EMPTY_PRIVILEGE()]);

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

      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="md">
        <DialogTitle>Create custom MongoDB role</DialogTitle>
        <DialogContent
          sx={{
            display: "grid",
            gap: 2,
            pt: "16px !important",
            maxHeight: "70vh",
            overflowY: "auto",
          }}
        >
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
              <Box sx={{ display: "grid", gap: 1.5 }}>
                {privileges.map((priv, i) => (
                  <PrivilegeEntry
                    key={i}
                    priv={priv}
                    index={i}
                    onChange={handlePrivilegeChange}
                    onRemove={handlePrivilegeRemove}
                    disabled={loading}
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
