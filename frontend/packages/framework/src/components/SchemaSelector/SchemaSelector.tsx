import { useQuery } from '@tanstack/react-query';
import { useWatch, type Control } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import { SelectInput } from '@percona/percona-ui';

interface SchemaInfo {
  schemaName: string;
}

interface SchemaSelectorProps {
  name: string;
  label: string;
  required?: boolean;
  dependsOn: string;
  control: Control;
}

// TODO: connect to real inventory API
const MOCK_SCHEMAS: Record<string, SchemaInfo[]> = {
  'svc-1': [{ schemaName: 'app_production' }, { schemaName: 'app_analytics' }],
  'svc-2': [{ schemaName: 'app_staging' }],
  'svc-3': [{ schemaName: 'public' }, { schemaName: 'analytics' }],
};

export function SchemaSelector({ name, label, required, dependsOn, control }: SchemaSelectorProps) {
  const serviceId = useWatch({ control, name: dependsOn }) as string | undefined;

  const { data: schemas = [], isLoading } = useQuery<SchemaInfo[]>({
    queryKey: ['inventory', 'schemas', serviceId],
    enabled: !!serviceId,
    queryFn: async () => {
      // TODO: switch to real API
      await new Promise((r) => setTimeout(r, 200));
      return (serviceId ? MOCK_SCHEMAS[serviceId] : undefined) ?? [];
    },
  });

  return (
    <SelectInput
      name={name}
      label={label}
      isRequired={required}
      control={control}
      helperText={
        !serviceId ? 'Select a service first' : isLoading ? 'Loading schemas...' : undefined
      }
      selectFieldProps={{ fullWidth: true, disabled: !serviceId }}
      controllerProps={{
        name,
        rules: {
          ...(required && { required: `${label} is required` }),
        },
      }}
    >
      {schemas.map((s) => (
        <MenuItem key={s.schemaName} value={s.schemaName}>
          {s.schemaName}
        </MenuItem>
      ))}
    </SelectInput>
  );
}
