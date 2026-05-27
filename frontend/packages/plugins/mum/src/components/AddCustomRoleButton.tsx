import { useState } from 'react';
import { apiClient } from '@sep/api';
import { Button } from '@mui/material';
import { RoleFormDialog } from './RoleFormDialog';
import type { RoleRow } from '../MumRoleList';
import type { ButtonProps } from '@mui/material';

interface AddCustomRoleButtonProps {
  selectedTarget: string;
  rolesData?: RoleRow[];
  onSuccess?: (meta: { role: string; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

export function AddCustomRoleButton({ selectedTarget, rolesData = [], onSuccess, buttonProps = {} }: AddCustomRoleButtonProps) {
  const [open, setOpen] = useState(false);

  const handleSubmit = async ({ role, db, privileges, inheritedRoles }: { role: string; db: string; privileges: unknown; inheritedRoles: unknown }) => {
    if (!selectedTarget) throw new Error('Select an executor host first.');
    // [MUM-REPLACE] begin — dispatch create-role task via SEP internal endpoint
    await apiClient.post('/mum/ui/create-role', { target: selectedTarget, role, db, privileges, inheritedRoles });
    // [MUM-REPLACE] end
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
}
