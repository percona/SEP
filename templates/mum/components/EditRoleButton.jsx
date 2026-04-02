import React, { useState, useMemo } from "react";
import apiClient from "../../../ui/apiClient";
import { Button } from "@mui/material";
import RoleFormDialog from "./RoleFormDialog";

// Convert raw MongoDB privilege objects → RoleFormDialog internal format.
const parsePrivileges = (rawPrivileges) => {
  if (!Array.isArray(rawPrivileges)) return [];
  return rawPrivileges.map((p) => {
    const resource = p.resource || {};
    if (resource.cluster === true) {
      return { resourceType: "cluster", resourceDb: "", resourceCollection: "", actions: Array.isArray(p.actions) ? p.actions : [] };
    }
    return {
      resourceType: "collection",
      resourceDb: resource.db || "",
      resourceCollection: resource.collection || "",
      actions: Array.isArray(p.actions) ? p.actions : [],
    };
  });
};

// Convert raw MongoDB role references → { role, db } objects.
const parseInheritedRoles = (rawRoles) => {
  if (!Array.isArray(rawRoles)) return [];
  return rawRoles
    .map((r) => {
      if (typeof r === "string") return { role: r, db: "admin" };
      if (r && (r.role || r.name)) return { role: r.role || r.name, db: r.db || "" };
      return null;
    })
    .filter(Boolean);
};

const EditRoleButton = ({
  row,
  selectedTarget,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}) => {
  const [open, setOpen] = useState(false);

  const initialValues = useMemo(() => ({
    role: row?.role || "",
    db: row?.db || "admin",
    privileges: parsePrivileges(row?.privileges),
    inheritedRoles: parseInheritedRoles(row?.roles || row?.inheritedRoles),
  }), [row]);

  const handleSubmit = async ({ role, db, privileges, inheritedRoles }) => {
    if (!selectedTarget) throw new Error("Select an executor host first.");
    await apiClient.post("/mum/ui/update-role", {
      target: selectedTarget,
      role,
      db,
      privileges,
      inheritedRoles,
    });
    setOpen(false);
    onSuccess?.({ role, db, target: selectedTarget });
  };

  return (
    <>
      <Button
        size="small"
        variant="outlined"
        color="primary"
        onClick={() => setOpen(true)}
        {...buttonProps}
      >
        EDIT
      </Button>
      <RoleFormDialog
        open={open}
        onClose={() => setOpen(false)}
        onSubmit={handleSubmit}
        initialValues={initialValues}
        rolesData={rolesData}
        title={`Edit role: ${row?.role}`}
        submitLabel="Save changes"
        editMode={true}
      />
    </>
  );
};

export default EditRoleButton;
