import type { Control } from 'react-hook-form';
import { useWatch } from 'react-hook-form';
import Box from '@mui/material/Box';
import MenuItem from '@mui/material/MenuItem';
import { SwitchInput, SelectInput } from '@percona/percona-ui';

interface AlertOnFailFieldProps {
  control: Control;
}

// TODO: fetch real alert providers from backend
const MOCK_PROVIDERS = [
  { value: 'email', label: 'Email' },
  { value: 'slack', label: 'Slack' },
  { value: 'pagerduty', label: 'PagerDuty' },
];

export function AlertOnFailField({ control }: AlertOnFailFieldProps) {
  const alertEnabled = useWatch({ control, name: 'alertOnFail' }) as boolean;

  return (
    <Box>
      <SwitchInput
        name="alertOnFail"
        label="Alert on failure"
        labelCaption="Send a notification when this task fails"
        control={control}
      />
      {alertEnabled && (
        <SelectInput
          name="alertProvider"
          label="Alert Provider"
          control={control}
          selectFieldProps={{ fullWidth: true }}
          controllerProps={{ name: 'alertProvider' }}
        >
          {MOCK_PROVIDERS.map((p) => (
            <MenuItem key={p.value} value={p.value}>
              {p.label}
            </MenuItem>
          ))}
        </SelectInput>
      )}
    </Box>
  );
}
