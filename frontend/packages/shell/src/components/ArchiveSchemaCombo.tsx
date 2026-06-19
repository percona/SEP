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

import { useFormContext, useWatch } from 'react-hook-form';
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';

/** An inventory option: a schema or table identified by its inventory id. */
export interface ArchiveComboOption {
  id: number;
  name: string;
}

export interface ArchiveSchemaComboProps {
  /**
   * react-hook-form field that holds the inventory id (an
   * {@link ArchiveComboOption} when picked, or the raw numeric id for an edit
   * default). Cleared to `''` when a custom name is typed.
   */
  idFieldName: string;
  /**
   * react-hook-form field that holds a manually-typed name. Cleared to `''`
   * when an inventory option is picked.
   */
  nameFieldName: string;
  label: string;
  /** Inventory options to offer alongside free-text entry. */
  options: ArchiveComboOption[];
  loading?: boolean;
  disabled?: boolean;
  helperText?: string;
  placeholder?: string;
  /**
   * Write the picked inventory id as a scalar number rather than the full
   * `{ id, name }` option object. Needed for wire fields whose schema type does
   * not unwrap options on submit (e.g. the Destination Table, an `IntegerField`,
   * unlike the Source schema/table which are `schema`/`table` types). Defaults to
   * `false` so the existing schema/table behaviour is unchanged.
   */
  emitScalarId?: boolean;
}

const getOptionLabel = (opt: ArchiveComboOption | string) =>
  typeof opt === 'string' ? opt : opt.name;

const isOptionEqualToValue = (a: ArchiveComboOption | string, b: ArchiveComboOption | string) =>
  typeof a !== 'string' && typeof b !== 'string' && a.id === b.id;

/**
 * A free-solo autocomplete that unifies the old "pick from inventory" and
 * "type a name" pair into one input. Picking an option writes the inventory id
 * (as an option object the payload layer unwraps to a scalar id on submit);
 * typing a value writes the manual name. The two writes are mutually exclusive
 * so the `source_db_id` XOR `source_db_name` wire contract — and validators
 * 5a / 5b — hold without any backend change.
 *
 * Reusable for both the schema and table selectors (and, later, the Destination
 * section) by pointing it at the relevant id / name field pair.
 */
export function ArchiveSchemaCombo({
  idFieldName,
  nameFieldName,
  label,
  options,
  loading,
  disabled,
  helperText,
  placeholder,
  emitScalarId = false,
}: ArchiveSchemaComboProps) {
  const { control, setValue } = useFormContext();

  const idValue = useWatch({ control, name: idFieldName }) as
    | ArchiveComboOption
    | number
    | string
    | null
    | undefined;
  const nameValue = useWatch({ control, name: nameFieldName }) as string | undefined;

  // Derive the option shown in the input from whichever wire field is set.
  let value: ArchiveComboOption | string | null = null;
  if (idValue && typeof idValue === 'object' && 'id' in idValue) {
    value = idValue;
  } else if (typeof idValue === 'number') {
    // Edit prefill stores a raw id. Show it only once its option has loaded —
    // never surface the bare numeric id (which would also mismatch `options`).
    value = options.find((o) => o.id === idValue) ?? null;
  } else if (typeof nameValue === 'string' && nameValue !== '') {
    value = nameValue;
  }

  const writeId = (option: ArchiveComboOption) => {
    setValue(idFieldName, emitScalarId ? option.id : option, {
      shouldDirty: true,
      shouldValidate: true,
    });
    setValue(nameFieldName, '', { shouldDirty: true, shouldValidate: true });
  };

  const writeName = (name: string) => {
    setValue(nameFieldName, name, { shouldDirty: true, shouldValidate: true });
    setValue(idFieldName, '', { shouldDirty: true, shouldValidate: true });
  };

  const clear = () => {
    setValue(idFieldName, '', { shouldDirty: true, shouldValidate: true });
    setValue(nameFieldName, '', { shouldDirty: true, shouldValidate: true });
  };

  return (
    <Autocomplete<ArchiveComboOption | string, false, false, true>
      freeSolo
      value={value}
      options={options}
      loading={loading}
      disabled={disabled}
      getOptionLabel={getOptionLabel}
      isOptionEqualToValue={isOptionEqualToValue}
      // Keep the typed text after blur so a freshly-typed custom name survives.
      clearOnBlur={false}
      selectOnFocus
      handleHomeEndKeys
      onChange={(_event, newValue) => {
        if (newValue === null) {
          clear();
        } else if (typeof newValue === 'string') {
          // freeSolo "create" (Enter on typed text).
          writeName(newValue);
        } else {
          writeId(newValue);
        }
      }}
      onInputChange={(_event, input, reason) => {
        // Live free typing → manual name. 'reset' / 'clear' are selection-driven
        // and handled by onChange, so ignore them here to avoid clobbering an id.
        if (reason === 'input') {
          writeName(input);
        }
      }}
      renderInput={(params) => (
        <TextField {...params} label={label} placeholder={placeholder} helperText={helperText} />
      )}
    />
  );
}
