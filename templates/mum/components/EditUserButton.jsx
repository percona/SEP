import React, { useMemo, useState } from "react";
import apiClient from "../../../ui/apiClient";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  OutlinedInput,
  Select,
  TextField,
  Typography,
} from "@mui/material";

const DEFAULT_DB = "admin";

const parseRoles = (roles) =>
  Array.isArray(roles)
    ? roles
        .map((role) => {
          if (typeof role === "string") return role;
          if (role && typeof role === "object") return role.role || role.name || null;
          return null;
        })
        .filter(Boolean)
    : [];

const EditUserButton = ({
  row,
  selectedTarget,
  builtinRoles,
  onSuccess,
  buttonProps = {},
}) => {
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
      onSuccess?.({ username, roles, db: rolesDb || DEFAULT_DB });
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
      <Dialog open={open} onClose={closeDialog} fullWidth maxWidth="sm">
        <DialogTitle>Edit MongoDB user</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: 2 }}>
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
          <FormControl fullWidth>
            <InputLabel id="edit-roles-label">Built-in roles</InputLabel>
            <Select
              labelId="edit-roles-label"
              multiple
              value={roles}
              onChange={(e) =>
                setRoles(
                  typeof e.target.value === "string"
                    ? e.target.value.split(",")
                    : e.target.value
                )
              }
              input={<OutlinedInput id="select-edit-roles" label="Built-in roles" />}
              renderValue={(selected) => (
                <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5 }}>
                  {selected.map((value) => (
                    <Chip key={value} label={value} />
                  ))}
                </Box>
              )}
              disabled={loading}
            >
              {builtinRoles.map((role) => (
                <MenuItem key={role} value={role}>
                  {role}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
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
