import { useQuery } from '@tanstack/react-query';
import { useWatch, type Control } from 'react-hook-form';
import MenuItem from '@mui/material/MenuItem';
import { SelectInput } from '@percona/percona-ui';

interface TableInfo {
  tableName: string;
}

interface TableSelectorProps {
  name: string;
  label: string;
  required?: boolean;
  dependsOn: string;
  control: Control;
}

// TODO: connect to real inventory API
const MOCK_TABLES: Record<string, TableInfo[]> = {
  app_production: [
    { tableName: 'users' },
    { tableName: 'orders' },
    { tableName: 'products' },
  ],
  app_analytics: [
    { tableName: 'events' },
    { tableName: 'sessions' },
  ],
  app_staging: [
    { tableName: 'users' },
    { tableName: 'orders' },
  ],
  public: [
    { tableName: 'accounts' },
    { tableName: 'transactions' },
  ],
};

export function TableSelector({
  name,
  label,
  required,
  dependsOn,
  control,
}: TableSelectorProps) {
  const schemaName = useWatch({ control, name: dependsOn }) as string | undefined;

  const { data: tables = [], isLoading } = useQuery<TableInfo[]>({
    queryKey: ['inventory', 'tables', schemaName],
    enabled: !!schemaName,
    queryFn: async () => {
      // TODO: switch to real API
      await new Promise((r) => setTimeout(r, 200));
      return MOCK_TABLES[schemaName!] ?? [];
    },
  });

  return (
    <SelectInput
      name={name}
      label={label}
      isRequired={required}
      control={control}
      helperText={
        !schemaName
          ? 'Select a schema first'
          : isLoading
            ? 'Loading tables...'
            : undefined
      }
      selectFieldProps={{ fullWidth: true, disabled: !schemaName }}
      controllerProps={{
        name,
        rules: {
          ...(required && { required: `${label} is required` }),
        },
      }}
    >
      {tables.map((t) => (
        <MenuItem key={t.tableName} value={t.tableName}>
          {t.tableName}
        </MenuItem>
      ))}
    </SelectInput>
  );
}
