import { useFormContext } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useHosts, type HostOption } from '../../hooks/useHosts';

const EMPTY_OPTIONS: HostOption[] = [];

export interface HostSelectorProps {
  /** react-hook-form field name. Stores a `HostOption | null`. */
  name: string;
  label: string;
  required?: boolean;
  disabled?: boolean;
  helperText?: string;
}

const getOptionLabel = (opt: HostOption | string) => (typeof opt === 'string' ? opt : opt.name);

const isOptionEqualToValue = (a: HostOption, b: HostOption) => a.id === b.id;

export function HostSelector({ name, label, required, disabled, helperText }: HostSelectorProps) {
  const {
    control,
    formState: { errors },
  } = useFormContext();

  const { data: hosts = EMPTY_OPTIONS, isLoading, isError, error } = useHosts();

  const empty = !isLoading && !isError && hosts.length === 0;

  const fieldError = errors[name]?.message as string | undefined;

  const text = fieldError
    ? fieldError
    : isError
      ? (error?.message ?? 'Failed to load hosts')
      : empty
        ? 'No hosts available'
        : helperText;

  return (
    <AutoCompleteInput<HostOption>
      name={name}
      label={label}
      control={control}
      isRequired={required}
      loading={isLoading}
      disabled={disabled || isError}
      options={hosts}
      controllerProps={{
        name,
        rules: required ? { required: `${label} is required` } : undefined,
      }}
      autoCompleteProps={{
        getOptionLabel,
        isOptionEqualToValue,
        noOptionsText: isLoading ? 'Loading hosts…' : 'No hosts available',
      }}
      textFieldProps={{ helperText: text, error: isError || !!fieldError }}
    />
  );
}
