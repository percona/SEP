import { useQuery } from '@tanstack/react-query';
import { useWatch, type Control } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import { SelectInput } from '@percona/percona-ui';

interface HostInfo {
  hostId: string;
  hostName: string;
}

interface HostSelectorProps {
  name: string;
  label: string;
  required?: boolean;
  dependsOn?: string;
  control: Control;
}

// TODO: connect to real inventory API (SEP-963)
const MOCK_HOSTS: Record<string, HostInfo[]> = {
  'svc-1': [
    { hostId: 'host-1', hostName: 'db-mysql-01.prod' },
    { hostId: 'host-2', hostName: 'db-mysql-02.prod' },
  ],
  'svc-2': [{ hostId: 'host-3', hostName: 'db-mysql-01.staging' }],
  'svc-3': [{ hostId: 'host-4', hostName: 'db-pg-01.prod' }],
  'svc-4': [{ hostId: 'host-5', hostName: 'db-mongo-01.prod' }],
};

const ALL_HOSTS: HostInfo[] = Object.values(MOCK_HOSTS).flat();

export function HostSelector({ name, label, required, dependsOn, control }: HostSelectorProps) {
  const serviceId = useWatch({ control, name: dependsOn ?? '__noop__' }) as string | undefined;
  const scoped = Boolean(dependsOn);

  const { data: hosts = [], isLoading } = useQuery<HostInfo[]>({
    queryKey: ['inventory', 'hosts', scoped ? serviceId : 'all'],
    enabled: scoped ? !!serviceId : true,
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 200));
      if (!scoped) {
        return ALL_HOSTS;
      }
      return (serviceId ? MOCK_HOSTS[serviceId] : undefined) ?? [];
    },
  });

  const disabled = scoped && !serviceId;
  const helperText = disabled
    ? 'Select a service first'
    : isLoading
      ? 'Loading hosts...'
      : undefined;

  return (
    <SelectInput
      name={name}
      label={label}
      isRequired={required}
      control={control}
      helperText={helperText}
      selectFieldProps={{ fullWidth: true, disabled }}
      controllerProps={{
        name,
        rules: {
          ...(required && { required: `${label} is required` }),
        },
      }}
    >
      {hosts.map((h) => (
        <MenuItem key={h.hostId} value={h.hostId}>
          {h.hostName}
        </MenuItem>
      ))}
    </SelectInput>
  );
}
