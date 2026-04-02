import React, { useMemo, useState } from "react";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  Divider,
  FormControl,
  FormControlLabel,
  FormGroup,
  FormLabel,
  TextField,
  Typography,
} from "@mui/material";

const normalizeArray = (value) => (Array.isArray(value) ? value : []);

// Stable key for any role item (string or {role, db} object)
const roleKey = (item) =>
  typeof item === "string" ? item : `${item.role}@${item.db}`;

const BuiltinRolesSelector = ({
  builtinRoles = [],
  customRoles = [],   // array of {role, db} objects from live rolesData
  value = [],
  onChange,
  disabled = false,
}) => {
  const [search, setSearch] = useState("");
  const roleOptions = useMemo(() => normalizeArray(builtinRoles), [builtinRoles]);
  const customOptions = useMemo(() => normalizeArray(customRoles), [customRoles]);
  const selected = useMemo(() => normalizeArray(value), [value]);
  const selectedKeys = useMemo(() => new Set(selected.map(roleKey)), [selected]);

  const lowerSearch = search.trim().toLowerCase();

  const filteredBuiltin = useMemo(
    () =>
      lowerSearch
        ? roleOptions.filter((r) => r.toLowerCase().includes(lowerSearch))
        : roleOptions,
    [roleOptions, lowerSearch]
  );

  const filteredCustom = useMemo(
    () =>
      lowerSearch
        ? customOptions.filter(
            (r) =>
              r.role.toLowerCase().includes(lowerSearch) ||
              (r.db || "").toLowerCase().includes(lowerSearch)
          )
        : customOptions,
    [customOptions, lowerSearch]
  );

  const toggleBuiltin = (role) => {
    if (selectedKeys.has(role)) {
      onChange?.(selected.filter((item) => roleKey(item) !== role));
    } else {
      onChange?.([...selected, role]);
    }
  };

  const toggleCustom = (roleObj) => {
    const key = roleKey(roleObj);
    if (selectedKeys.has(key)) {
      onChange?.(selected.filter((item) => roleKey(item) !== key));
    } else {
      onChange?.([...selected, { role: roleObj.role, db: roleObj.db }]);
    }
  };

  const handleClear = () => onChange?.([]);

  return (
    <FormControl component="fieldset" fullWidth>
      <FormLabel sx={{ mb: 1 }}>Roles</FormLabel>
      <TextField
        label="Search roles"
        placeholder="Start typing to filter…"
        size="small"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        disabled={disabled}
      />

      <Box
        sx={{
          mt: 1,
          border: (theme) => `1px solid ${theme.palette.divider}`,
          borderRadius: 1,
          maxHeight: 280,
          overflowY: "auto",
          p: 1,
        }}
      >
        {/* Built-in roles */}
        {filteredBuiltin.length > 0 && (
          <>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Built-in
            </Typography>
            <FormGroup
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "repeat(1, minmax(0, 1fr))",
                  sm: "repeat(2, minmax(0, 1fr))",
                  md: "repeat(3, minmax(0, 1fr))",
                },
                columnGap: 1,
                rowGap: 0.5,
              }}
            >
              {filteredBuiltin.map((role) => (
                <FormControlLabel
                  key={role}
                  control={
                    <Checkbox
                      checked={selectedKeys.has(role)}
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

        {/* Custom roles */}
        {filteredCustom.length > 0 && (
          <>
            {filteredBuiltin.length > 0 && <Divider sx={{ my: 1 }} />}
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              Custom
            </Typography>
            <FormGroup
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "repeat(1, minmax(0, 1fr))",
                  sm: "repeat(2, minmax(0, 1fr))",
                  md: "repeat(3, minmax(0, 1fr))",
                },
                columnGap: 1,
                rowGap: 0.5,
              }}
            >
              {filteredCustom.map((r) => {
                const key = roleKey(r);
                return (
                  <FormControlLabel
                    key={key}
                    control={
                      <Checkbox
                        checked={selectedKeys.has(key)}
                        onChange={() => toggleCustom(r)}
                        disabled={disabled}
                        size="small"
                      />
                    }
                    label={
                      <Typography variant="body2">
                        {r.role}
                        {r.db ? (
                          <Typography component="span" variant="caption" color="text.secondary">
                            {" "}@ {r.db}
                          </Typography>
                        ) : null}
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
            {roleOptions.length + customOptions.length > 0
              ? `No roles match "${search}".`
              : "No roles available."}
          </Typography>
        )}
      </Box>

      {selected.length > 0 && (
        <>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
            Selected
          </Typography>
          <Box sx={{ display: "flex", flexWrap: "wrap", gap: 0.5, mt: 0.5 }}>
            {selected.map((item) => {
              const key = roleKey(item);
              const label =
                typeof item === "string"
                  ? item
                  : item.db
                  ? `${item.role} @ ${item.db}`
                  : item.role;
              return (
                <Chip
                  key={key}
                  label={label}
                  size="small"
                  onDelete={
                    disabled
                      ? undefined
                      : () =>
                          typeof item === "string"
                            ? toggleBuiltin(item)
                            : toggleCustom(item)
                  }
                />
              );
            })}
          </Box>
        </>
      )}

      <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end", mt: 1 }}>
        <Button
          size="small"
          color="secondary"
          onClick={handleClear}
          disabled={disabled || selected.length === 0}
        >
          Clear roles
        </Button>
      </Box>
    </FormControl>
  );
};

export default BuiltinRolesSelector;
