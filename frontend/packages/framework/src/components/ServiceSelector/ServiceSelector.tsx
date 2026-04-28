import { useMemo } from 'react';
import type { Control } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useServices, type ServiceOption, type ServiceType } from '../../hooks/useServices';

const EMPTY_OPTIONS: ServiceOption[] = [];

export interface ServiceSelectorProps {
  /** react-hook-form field name. Stores a `ServiceOption | null`. */
  name: string;
  label: string;
  required?: boolean;
  /** Optional filter — only services whose `type` is in this list are shown. */
  serviceTypes?: readonly ServiceType[];
  /** Optional explicit form `control`. Falls back to `useFormContext`. */
  control?: Control;
  disabled?: boolean;
  helperText?: string;
}

const getOptionLabel = (opt: ServiceOption | string) =>
  typeof opt === 'string' ? opt : `${opt.name} (${opt.type})`;

const isOptionEqualToValue = (a: ServiceOption, b: ServiceOption) => a.id === b.id;

export function ServiceSelector({
  name,
  label,
  required,
  serviceTypes,
  control,
  disabled,
  helperText,
}: ServiceSelectorProps) {
  // Stabilise the array reference so `useServices` query key stays stable
  // across renders when the parent passes a fresh literal each time.
  const types = useMemo(
    () => (serviceTypes && serviceTypes.length > 0 ? Array.from(serviceTypes) : undefined),
    // Compare as a sorted, joined string so [a, b] and [b, a] dedupe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [serviceTypes ? [...serviceTypes].sort().join('|') : ''],
  );

  const {
    data: services = EMPTY_OPTIONS,
    isLoading,
    isError,
    error,
  } = useServices({ serviceTypes: types });

  const empty = !isLoading && !isError && services.length === 0;

  const text = isError
    ? (error?.message ?? 'Failed to load services')
    : empty
      ? 'No services available'
      : helperText;

  return (
    <AutoCompleteInput<ServiceOption>
      name={name}
      label={label}
      control={control}
      isRequired={required}
      loading={isLoading}
      disabled={disabled || isError}
      options={services}
      controllerProps={{
        name,
        rules: required ? { required: `${label} is required` } : undefined,
      }}
      autoCompleteProps={{
        getOptionLabel,
        isOptionEqualToValue,
        noOptionsText: isLoading ? 'Loading services…' : 'No services',
      }}
      textFieldProps={{ helperText: text, error: isError }}
    />
  );
}
