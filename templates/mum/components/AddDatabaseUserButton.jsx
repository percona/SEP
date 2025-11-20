import React, { useState } from "react";
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
  OutlinedInput,
  Select,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";

const DEFAULT_DB = "admin";

const AddDatabaseUserButton = ({
  selectedTarget,
  builtinRoles,
  getCsrfToken,
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

  const resetForm = () => {
    setUsername("");
    setPassword("");
    setRoles([]);
    setRolesDb(DEFAULT_DB);
    setError(null);
  };

  const handleOpen = () => {
    resetForm();
    setOpen(true);
  };

  const handleClose = () => {
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
    if (!password || roles.length === 0) {
      setError("Password and at least one role are required.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await apiClient.post("/mum/ui/create-user", {
        target: selectedTarget,
        username,
        password,
        roles,
        db: rolesDb || DEFAULT_DB,
        ["csrf-token"]: getCsrfToken?.(),
      });
      setOpen(false);
      onSuccess?.({ username, roles, db: rolesDb || DEFAULT_DB });
      resetForm();
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Failed to create user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button variant="contained" color="success" onClick={handleOpen} {...buttonProps}>
        + add database user
      </Button>
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="sm">
        <DialogTitle>Create MongoDB user</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: 2 }}>
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
          <FormControl fullWidth>
            <InputLabel id="add-roles-label">Built-in roles</InputLabel>
            <Select
              labelId="add-roles-label"
              multiple
              value={roles}
              onChange={(e) =>
                setRoles(
                  typeof e.target.value === "string"
                    ? e.target.value.split(",")
                    : e.target.value
                )
              }
              input={<OutlinedInput id="select-add-roles" label="Built-in roles" />}
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
          <Button onClick={handleClose} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} variant="contained" color="success" disabled={loading}>
            {loading ? "Creating…" : "Create"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default AddDatabaseUserButton;
