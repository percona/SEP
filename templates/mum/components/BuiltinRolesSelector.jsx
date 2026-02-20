import React, { useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  TextField,
  Typography,
} from "@mui/material";

const normalizeArray = (value) => (Array.isArray(value) ? value : []);

const BuiltinRolesSelector = ({
  builtinRoles = [],
  value = [],
  onChange,
  disabled = false,
}) => {
  const [search, setSearch] = useState("");
  const roleOptions = useMemo(() => normalizeArray(builtinRoles), [builtinRoles]);
  const selectedRoles = useMemo(() => normalizeArray(value), [value]);
  const lowerSearch = search.trim().toLowerCase();

  const filteredRoles = useMemo(() => {
    if (!lowerSearch) {
      return roleOptions;
    }
    return roleOptions.filter((role) =>
      role.toLowerCase().includes(lowerSearch)
    );
  }, [roleOptions, lowerSearch]);

  const emitChange = (nextValue) => {
    onChange?.(nextValue);
  };

  const toggleRole = (role) => {
    if (selectedRoles.includes(role)) {
      emitChange(selectedRoles.filter((item) => item !== role));
      return;
    }
    emitChange([...selectedRoles, role]);
  };

  const handleClear = () => emitChange([]);
  const handleSelectAll = () => emitChange([...roleOptions]);

  return (
    <FormControl component="fieldset" fullWidth>
      <FormLabel sx={{ mb: 1 }}>Built-in roles</FormLabel>
      <TextField
        label="Search roles"
        placeholder="Start typing to filter…"
        size="small"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        disabled={disabled}
      />

      <Box
        sx={{
          mt: 1,
          border: (theme) => `1px solid ${theme.palette.divider}`,
          borderRadius: 1,
          maxHeight: 240,
          overflowY: "auto",
          p: 1,
        }}
      >
        <FormGroup
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "repeat(1, minmax(0, 1fr))",
              sm: "repeat(2, minmax(0, 1fr))",
            },
            columnGap: 1,
            rowGap: 0.5,
          }}
        >
          {filteredRoles.map((role) => (
            <FormControlLabel
              key={role}
              control={
                <Checkbox
                  checked={selectedRoles.includes(role)}
                  onChange={() => toggleRole(role)}
                  disabled={disabled}
                  size="small"
                />
              }
              label={role}
              disabled={disabled}
            />
          ))}
          {!filteredRoles.length && (
            <Typography
              sx={{ gridColumn: "1 / -1", py: 1 }}
              variant="body2"
              color="text.secondary"
            >
              {roleOptions.length
                ? `No roles match “${search}”.`
                : "No built-in roles available."}
            </Typography>
          )}
        </FormGroup>
      </Box>

      {Boolean(selectedRoles.length) && (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
            Selected roles
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
            {selectedRoles.map((role) => (
              <Chip
                key={role}
                label={role}
                size="small"
                onDelete={
                  disabled ? undefined : () => toggleRole(role)
                }
              />
            ))}
          </Box>
        </>
      )}

      <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end", mt: 1 }}>
        <Button
          size="small"
          color="secondary"
          onClick={handleClear}
          disabled={disabled || selectedRoles.length === 0}
        >
          Clear roles
        </Button>
        <Button
          size="small"
          onClick={handleSelectAll}
          disabled={
            disabled ||
            !roleOptions.length ||
            selectedRoles.length === roleOptions.length
          }
        >
          Select all
        </Button>
      </Box>
    </FormControl>
  );
};

export default BuiltinRolesSelector;
