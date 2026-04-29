import { useEffect, useRef } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useSchemas, type SchemaOption } from '../../hooks/useSchemas';
import type { ServiceOption } from '../../hooks/useServices';
import { extractId } from '../../utils/extractId';

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
  disabled?: boolean;
}

const getOptionLabel = (opt: SchemaOption | string) => (typeof opt === 'string' ? opt : opt.name);

const isOptionEqualToValue = (a: SchemaOption, b: SchemaOption) => a.id === b.id;

export function SchemaSelector({
  name,
  label,
  required,
  dependsOn,
  disabled,
}: SchemaSelectorProps) {
  const { control, setValue } = useFormContext();

  const parent = useWatch({ control, name: dependsOn }) as
    | ServiceOption
    | number
    | null
    | undefined;
  const serviceId = extractId(parent);

  const prevIdRef = useRef<number | null>(serviceId);
  useEffect(() => {
    if (prevIdRef.current !== serviceId) {
      prevIdRef.current = serviceId;
      setValue(name, null, { shouldDirty: true, shouldValidate: false });
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
      control={control}
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
            : 'No schemas in this service',
      }}
      textFieldProps={{ helperText, error: isError }}
    />
  );
}
