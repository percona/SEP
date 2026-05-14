/**
 * Copyright (C) 2026 Percona LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

import { useEffect, useRef } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useTables, type TableOption } from '../../hooks/useTables';
import type { SchemaOption } from '../../hooks/useSchemas';
import { extractId } from '../../utils/extractId';

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
  disabled?: boolean;
}

const getOptionLabel = (opt: TableOption | string) => (typeof opt === 'string' ? opt : opt.name);

const isOptionEqualToValue = (a: TableOption, b: TableOption) => a.id === b.id;

export function TableSelector({ name, label, required, dependsOn, disabled }: TableSelectorProps) {
  const { control, setValue } = useFormContext();

  const parent = useWatch({ control, name: dependsOn }) as SchemaOption | number | null | undefined;
  const schemaId = extractId(parent);

  const prevIdRef = useRef<number | null>(schemaId);
  useEffect(() => {
    if (prevIdRef.current !== schemaId) {
      prevIdRef.current = schemaId;
      setValue(name, null, { shouldDirty: true, shouldValidate: false });
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
      control={control}
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
            : 'No tables in this schema',
      }}
      textFieldProps={{ helperText, error: isError }}
    />
  );
}
