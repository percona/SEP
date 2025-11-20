import React, { useState } from "react";
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

const DEFAULT_DB = "admin";

const DeleteUserButton = ({
  row,
  selectedTarget,
  getCsrfToken,
  onSuccess,
  buttonProps = {},
}) => {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [confirmText, setConfirmText] = useState("");

  const username = row?.user || row?.username || "";
  const dbName = row?.db || DEFAULT_DB;

  const handleOpen = () => {
    setConfirmText("");
    setError(null);
    setOpen(true);
  };

  const handleClose = () => {
    if (!loading) setOpen(false);
  };

  const handleDelete = async () => {
    if (!selectedTarget) {
      setError("Select an executor host first.");
      return;
    }
    if (confirmText !== "confirm") {
      setError("Type 'confirm' to proceed.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await apiClient.post("/mum/ui/delete-user", {
        target: selectedTarget,
        username,
        db: dbName || DEFAULT_DB,
        ["csrf-token"]: getCsrfToken?.(),
      });
      setOpen(false);
      onSuccess?.({ username, db: dbName || DEFAULT_DB });
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Failed to delete user");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <Button
        size="small"
        color="error"
        variant="outlined"
        onClick={handleOpen}
        {...buttonProps}
      >
        DELETE
      </Button>
      <Dialog open={open} onClose={handleClose} fullWidth maxWidth="xs">
        <DialogTitle>Delete MongoDB user</DialogTitle>
        <DialogContent sx={{ display: "grid", gap: 2, pt: 2 }}>
          <Typography variant="body2">
            You are about to delete user <strong>{username}</strong> from DB{" "}
            <code>{dbName}</code>.
          </Typography>
          <TextField
            label="Type 'confirm' to proceed"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            disabled={loading}
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
          <Button onClick={handleDelete} variant="contained" color="error" disabled={loading}>
            {loading ? "Deleting…" : "Delete"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
};

export default DeleteUserButton;
