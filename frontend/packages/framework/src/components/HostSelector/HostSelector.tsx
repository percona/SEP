import { useEffect, useRef } from 'react';
import { useFormContext } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useSnackbar } from 'notistack';
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
  const { enqueueSnackbar } = useSnackbar();

  const { data, isLoading, isError, error } = useHosts();
  const hosts = data?.hosts ?? EMPTY_OPTIONS;
  const upstreamError = data?.upstreamError ?? null;

  const empty = !isLoading && !isError && hosts.length === 0;

  const fieldError = errors[name]?.message as string | undefined;

  // Surface upstream Tasks-API failures via the shell's snackbar system. The
  // route returns `200 []` with the detail attached as a header so the
  // dropdown can still render "No hosts available" while the user gets a
  // visible explanation. Raise once per distinct upstream error message.
  const lastSurfacedRef = useRef<string | null>(null);
  useEffect(() => {
    if (upstreamError && upstreamError !== lastSurfacedRef.current) {
      enqueueSnackbar(`Failed to load executor hosts: ${upstreamError}`, {
        variant: 'error',
        autoHideDuration: 30_000,
      });
      lastSurfacedRef.current = upstreamError;
    }
  }, [upstreamError, enqueueSnackbar]);

  let text = helperText;
  if (fieldError) {
    text = fieldError;
  } else if (isError) {
    text = error?.message ?? 'Failed to load hosts';
  } else if (empty) {
    text = 'No hosts available';
  }

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
