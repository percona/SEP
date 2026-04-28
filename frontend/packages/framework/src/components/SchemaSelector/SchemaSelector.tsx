import { useEffect, useRef } from 'react';
import { useFormContext, useWatch, type Control } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useSchemas, type SchemaOption } from '../../hooks/useSchemas';
import type { ServiceOption } from '../../hooks/useServices';

const EMPTY_OPTIONS: SchemaOption[] = [];

export interface SchemaSelectorProps {
  /** react-hook-form field name. Stores a `SchemaOption | null`. */
  name: string;
  label: string;
  required?: boolean;
  /**
   * Form field name of the parent `ServiceSelector`. The watched value is
   * either a `ServiceOption` (from `<ServiceSelector>`) or a raw service id.
   */
  dependsOn: string;
  control?: Control;
  disabled?: boolean;
}

const getOptionLabel = (opt: SchemaOption | string) => (typeof opt === 'string' ? opt : opt.name);

const isOptionEqualToValue = (a: SchemaOption, b: SchemaOption) => a.id === b.id;

function extractId(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value !== '') {
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }
  if (value && typeof value === 'object' && 'id' in value) {
    return extractId((value as { id: unknown }).id);
  }
  return null;
}

export function SchemaSelector({
  name,
  label,
  required,
  dependsOn,
  control,
  disabled,
}: SchemaSelectorProps) {
  const ctx = useFormContext();
  const effectiveControl = control ?? ctx?.control;
  const setValue = ctx?.setValue;

  const parent = useWatch({ control: effectiveControl, name: dependsOn }) as
    | ServiceOption
    | number
    | null
    | undefined;
  const serviceId = extractId(parent);

  // Reset child whenever the parent service id changes.
  const prevIdRef = useRef<number | null>(serviceId);
  useEffect(() => {
    if (prevIdRef.current !== serviceId) {
      prevIdRef.current = serviceId;
      if (setValue) {
        setValue(name, null, { shouldDirty: true, shouldValidate: false });
      }
    }
  }, [serviceId, name, setValue]);

  const { data: schemas = EMPTY_OPTIONS, isLoading, isError, error } = useSchemas({ serviceId });

  const noService = serviceId === null || serviceId === undefined;
  const empty = !noService && !isLoading && !isError && schemas.length === 0;

  const helperText = noService
    ? 'Select a service first'
    : isError
      ? (error?.message ?? 'Failed to load schemas')
      : empty
        ? 'No schemas in this service'
        : undefined;

  return (
    <AutoCompleteInput<SchemaOption>
      name={name}
      label={label}
      control={effectiveControl}
      isRequired={required}
      loading={isLoading}
      disabled={disabled || noService || isError}
      options={schemas}
      controllerProps={{
        name,
        rules: required ? { required: `${label} is required` } : undefined,
      }}
      autoCompleteProps={{
        getOptionLabel,
        isOptionEqualToValue,
        noOptionsText: noService
          ? 'Select a service first'
          : isLoading
            ? 'Loading schemas…'
            : 'No schemas',
      }}
      textFieldProps={{ helperText, error: isError }}
    />
  );
}
