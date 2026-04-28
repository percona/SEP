import { useEffect, useRef } from 'react';
import { useFormContext, useWatch, type Control } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useTables, type TableOption } from '../../hooks/useTables';
import type { SchemaOption } from '../../hooks/useSchemas';
import { extractId } from '../../hooks/extractId';

const EMPTY_OPTIONS: TableOption[] = [];

export interface TableSelectorProps {
  /** react-hook-form field name. Stores a `TableOption | null`. */
  name: string;
  label: string;
  required?: boolean;
  /**
   * Form field name of the parent `SchemaSelector`. The watched value is
   * either a `SchemaOption` or a raw schema id.
   */
  dependsOn: string;
  control?: Control;
  disabled?: boolean;
}

const getOptionLabel = (opt: TableOption | string) => (typeof opt === 'string' ? opt : opt.name);

const isOptionEqualToValue = (a: TableOption, b: TableOption) => a.id === b.id;

export function TableSelector({
  name,
  label,
  required,
  dependsOn,
  control,
  disabled,
}: TableSelectorProps) {
  const ctx = useFormContext();
  const effectiveControl = control ?? ctx?.control;
  const setValue = ctx?.setValue;

  const parent = useWatch({ control: effectiveControl, name: dependsOn }) as
    | SchemaOption
    | number
    | null
    | undefined;
  const schemaId = extractId(parent);

  const prevIdRef = useRef<number | null>(schemaId);
  useEffect(() => {
    if (prevIdRef.current !== schemaId) {
      prevIdRef.current = schemaId;
      if (setValue) {
        setValue(name, null, { shouldDirty: true, shouldValidate: false });
      }
    }
  }, [schemaId, name, setValue]);

  const { data: tables = EMPTY_OPTIONS, isLoading, isError, error } = useTables({ schemaId });

  const noSchema = schemaId === null || schemaId === undefined;
  const empty = !noSchema && !isLoading && !isError && tables.length === 0;

  const helperText = noSchema
    ? 'Select a schema first'
    : isError
      ? (error?.message ?? 'Failed to load tables')
      : empty
        ? 'No tables in this schema'
        : undefined;

  return (
    <AutoCompleteInput<TableOption>
      name={name}
      label={label}
      control={effectiveControl}
      isRequired={required}
      loading={isLoading}
      disabled={disabled || noSchema || isError}
      options={tables}
      controllerProps={{
        name,
        rules: required ? { required: `${label} is required` } : undefined,
      }}
      autoCompleteProps={{
        getOptionLabel,
        isOptionEqualToValue,
        noOptionsText: noSchema
          ? 'Select a schema first'
          : isLoading
            ? 'Loading tables…'
            : 'No tables',
      }}
      textFieldProps={{ helperText, error: isError }}
    />
  );
}
