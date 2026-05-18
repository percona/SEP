import { useState, useMemo } from 'react';
import { apiClient } from '@sep/api';
import { Button } from '@mui/material';
import { RoleFormDialog } from './RoleFormDialog';
import type { RoleRow } from '../MumRoleList';
import type { PrivilegeForm } from './RoleFormDialog';
import type { ButtonProps } from '@mui/material';

interface EditRoleButtonProps {
  row: RoleRow;
  selectedTarget: string;
  rolesData?: RoleRow[];
  onSuccess?: (meta: { role: string; db: string; target: string }) => void;
  buttonProps?: Partial<ButtonProps>;
}

const parsePrivileges = (rawPrivileges: unknown): PrivilegeForm[] => {
  if (!Array.isArray(rawPrivileges)) return [];
  return rawPrivileges.map((p) => {
    const resource = (p as Record<string, unknown>)?.['resource'] as Record<string, unknown> | undefined ?? {};
    if (resource['cluster'] === true) {
      return { resourceType: 'cluster' as const, resourceDb: '', resourceCollection: '', actions: Array.isArray((p as Record<string, unknown>)['actions']) ? (p as Record<string, unknown>)['actions'] as string[] : [] };
    }
    return {
      resourceType: 'collection' as const,
      resourceDb: String(resource['db'] ?? ''),
      resourceCollection: String(resource['collection'] ?? ''),
      actions: Array.isArray((p as Record<string, unknown>)['actions']) ? (p as Record<string, unknown>)['actions'] as string[] : [],
    };
  });
};

const parseInheritedRoles = (rawRoles: unknown): Array<{ role: string; db: string }> => {
  if (!Array.isArray(rawRoles)) return [];
  return rawRoles
    .map((r) => {
      if (typeof r === 'string') return { role: r, db: 'admin' };
      if (r && typeof r === 'object') {
        const obj = r as Record<string, unknown>;
        if (obj['role'] || obj['name']) return { role: String(obj['role'] ?? obj['name']), db: String(obj['db'] ?? '') };
      }
      return null;
    })
    .filter((r): r is { role: string; db: string } => r !== null);
};

export function EditRoleButton({ row, selectedTarget, rolesData = [], onSuccess, buttonProps = {} }: EditRoleButtonProps) {
  const [open, setOpen] = useState(false);

  const initialValues = useMemo(() => ({
    role: String(row?.['role'] ?? ''),
    db: String(row?.['db'] ?? 'admin'),
    privileges: parsePrivileges(row?.['privileges']),
    inheritedRoles: parseInheritedRoles(row?.['roles'] ?? row?.['inheritedRoles']),
  }), [row]);

  const handleSubmit = async ({ role, db, privileges, inheritedRoles }: { role: string; db: string; privileges: unknown; inheritedRoles: unknown }) => {
    if (!selectedTarget) throw new Error('Select an executor host first.');
    await apiClient.post('/mum/ui/update-role', { target: selectedTarget, role, db, privileges, inheritedRoles });
    setOpen(false);
    onSuccess?.({ role, db, target: selectedTarget });
  };

  return (
    <>
      <Button size="small" variant="outlined" color="primary" onClick={() => setOpen(true)} {...buttonProps}>EDIT</Button>
      <RoleFormDialog
        open={open}
        onClose={() => setOpen(false)}
        onSubmit={handleSubmit}
        initialValues={initialValues}
        rolesData={rolesData}
        title={`Edit role: ${String(row?.['role'] ?? '')}`}
        submitLabel="Save changes"
        editMode={true}
      />
    </>
  );
}
