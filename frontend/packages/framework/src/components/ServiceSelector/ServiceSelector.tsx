import { useQuery } from '@tanstack/react-query';
import type { Control } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import { SelectInput } from '@percona/percona-ui';

interface Service {
  serviceId: string;
  serviceName: string;
  serviceType: string;
}

interface ServiceSelectorProps {
  name: string;
  label: string;
  required?: boolean;
  serviceTypes?: string[];
  control: Control;
}

// TODO: connect to real inventory API
const MOCK_SERVICES: Service[] = [
  { serviceId: 'svc-1', serviceName: 'mysql-prod-1', serviceType: 'mysql' },
  { serviceId: 'svc-2', serviceName: 'mysql-staging-1', serviceType: 'mysql' },
  { serviceId: 'svc-3', serviceName: 'postgres-prod-1', serviceType: 'postgresql' },
  { serviceId: 'svc-4', serviceName: 'mongo-prod-1', serviceType: 'mongodb' },
];

export function ServiceSelector({
  name,
  label,
  required,
  serviceTypes,
  control,
}: ServiceSelectorProps) {
  const { data: services = [], isLoading } = useQuery<Service[]>({
    queryKey: ['inventory', 'services', serviceTypes],
    queryFn: async () => {
      // TODO: switch to real API
      await new Promise((r) => setTimeout(r, 200));
      const filtered = serviceTypes?.length
        ? MOCK_SERVICES.filter((s) => serviceTypes.includes(s.serviceType))
        : MOCK_SERVICES;
      return filtered;
    },
    placeholderData: MOCK_SERVICES,
  });

  return (
    <SelectInput
      name={name}
      label={label}
      isRequired={required}
      control={control}
      helperText={isLoading ? 'Loading services...' : undefined}
      selectFieldProps={{ fullWidth: true }}
      controllerProps={{
        name,
        rules: {
          ...(required && { required: `${label} is required` }),
        },
      }}
    >
      {services.map((svc) => (
        <MenuItem key={svc.serviceId} value={svc.serviceId}>
          {svc.serviceName} ({svc.serviceType})
        </MenuItem>
      ))}
    </SelectInput>
  );
}
