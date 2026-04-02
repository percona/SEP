import React, { useMemo, useState } from "react";
import apiClient from "../../../ui/apiClient";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
} from "@mui/material";
import BuiltinRolesSelector from "./BuiltinRolesSelector";

const DEFAULT_DB = "admin";

// Preserve {role, db} objects from MongoDB; fall back to string for plain names.
const parseRoles = (roles) =>
  Array.isArray(roles)
    ? roles
        .map((role) => {
          if (typeof role === "string") return role;
          if (role && typeof role === "object" && (role.role || role.name)) {
            return { role: role.role || role.name, db: role.db || "" };
          }
          return null;
        })
        .filter(Boolean)
    : [];

const EditUserButton = ({
  row,
  selectedTarget,
  builtinRoles,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}) => {
  const customRoles = rolesData.filter((r) => !r.isBuiltin && r.role);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState([]);
  const [rolesDb, setRolesDb] = useState(DEFAULT_DB);

  const initialValues = useMemo(() => {
    const usernameValue = row?.user || row?.username || "";
    const rolesValue = parseRoles(row?.roles);
    const dbValue = row?.db || DEFAULT_DB;
    return { usernameValue, rolesValue, dbValue };
  }, [row]);

  const openDialog = () => {
    setUsername(initialValues.usernameValue);
    setRoles(initialValues.rolesValue);
    setRolesDb(initialValues.dbValue);
    setPassword("");
    setError(null);
    setOpen(true);
  };

  const closeDialog = () => {
    if (!loading) setOpen(false);
  };

  const handleSubmit = async () => {
    if (!selectedTarget) {
      setError("Select an executor host first.");
      return;
    }
    if (!username) {
      setError("Username is required.");
      return;
    }
    if (roles.length === 0) {
      setError("At least one role is required.");
      return;
    }
    setLoading(true);
    setError(null);

    try {
      const body = {
        target: selectedTarget,
        username,
        db: rolesDb || DEFAULT_DB,
        roles,
      };
      if (password) body.password = password;
      await apiClient.post("/mum/ui/update-user", body);
      setOpen(false);
      onSuccess?.({ username, roles, db: rolesDb || DEFAULT_DB, target: selectedTarget });
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Failed to update user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button size="small" variant="outlined" onClick={openDialog} {...buttonProps}>
        EDIT
      </Button>
      <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="md" scroll="paper" disableScrollLock>
        <DialogTitle>Edit MongoDB user</DialogTitle>
        <DialogContent dividers sx={{ display: "grid", gap: 2 }}>
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
          {error && (
            <Typography color="error" variant="body2">
              {error}
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDialog} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} variant="contained" color="success" disabled={loading}>
            {loading ? "Saving…" : "Save"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default EditUserButton;
