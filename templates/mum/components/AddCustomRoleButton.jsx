import React, { useState } from "react";
import apiClient from "../../../ui/apiClient";
import { Button } from "@mui/material";
import RoleFormDialog from "./RoleFormDialog";

const AddCustomRoleButton = ({
  selectedTarget,
  rolesData = [],
  onSuccess,
  buttonProps = {},
}) => {
  const [open, setOpen] = useState(false);

  const handleSubmit = async ({ role, db, privileges, inheritedRoles }) => {
    if (!selectedTarget) throw new Error("Select an executor host first.");
    await apiClient.post("/mum/ui/create-role", {
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
      <Button variant="contained" color="success" onClick={() => setOpen(true)} {...buttonProps}>
        + add custom role
      </Button>
      <RoleFormDialog
        open={open}
        onClose={() => setOpen(false)}
        onSubmit={handleSubmit}
        initialValues={null}
        rolesData={rolesData}
        title="Create custom MongoDB role"
        submitLabel="Create role"
        editMode={false}
      />
    </>
  );
};

export default AddCustomRoleButton;
