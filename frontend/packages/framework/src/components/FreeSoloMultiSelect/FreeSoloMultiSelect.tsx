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

import { useEffect, useMemo } from 'react';
import {
  useFormContext,
  Controller,
  type ControllerRenderProps,
  type FieldError,
  type FieldValues,
} from 'react-hook-form';
import Autocomplete, { createFilterOptions } from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import TextField from '@mui/material/TextField';
import {
  normalizeMultiChange,
  toDisplayValues,
  type MultiReferenceOption,
} from './freeSoloMultiValue';

export interface FreeSoloMultiSelectProps<T extends MultiReferenceOption> {
  /** react-hook-form field name. Stores `(number | string)[]` (inventory ids and/or free-typed values). */
  name: string;
  label: string;
  options: readonly T[];
  /** Label shown for an inventory option (e.g. `name`, or `name (type)`). */
  getOptionLabel: (option: T) => string;
  /**
   * When `true`, the user may add free-typed values alongside inventory picks
   * (free-solo multi-select). When `false`, only inventory options are
   * selectable (closed multi-select combobox) — typed text offers no "create"
   * suggestion and is not committed.
   */
  allowCustom: boolean;
  required?: boolean;
  disabled?: boolean;
  loading?: boolean;
  helperText?: string;
  error?: boolean;
  noOptionsText?: string;
  /** Called when the dropdown opens (e.g. to refetch option lists). */
  onOpen?: () => void;
}

const isOptionEqualToValue = <T extends MultiReferenceOption>(
  option: T | string,
  value: T | string,
): boolean =>
  typeof option === 'string' || typeof value === 'string'
    ? option === value
    : option.id === value.id;

/**
 * Inner Autocomplete, split out so it can hold hooks (`useEffect`/`useMemo`)
 * driven by the Controller's `field`.
 */
function FreeSoloMultiAutocomplete<T extends MultiReferenceOption>({
  field,
  fieldError,
  label,
  options,
  getOptionLabel,
  allowCustom,
  required,
  disabled,
  loading,
  onOpen,
  helperText,
  error,
  noOptionsText,
}: Omit<FreeSoloMultiSelectProps<T>, 'name'> & {
  field: ControllerRenderProps<FieldValues, string>;
  fieldError?: FieldError;
}) {
  const filter = useMemo(() => createFilterOptions<T | string>(), []);

  const labelOf = (option: T | string): string =>
    typeof option === 'string' ? option : getOptionLabel(option);

  const { value: fieldValue, onChange } = field;

  // If a value was typed as a free string before its inventory options had
  // loaded, resolve it to the matching id once the options arrive — so an exact
  // label match commits the id, not the string, regardless of load timing.
  useEffect(() => {
    if (!Array.isArray(fieldValue)) {
      return;
    }
    let changed = false;
    const resolved = fieldValue.map((entry) => {
      if (typeof entry === 'string' && entry.trim() !== '') {
        const match = options.find((o) => getOptionLabel(o) === entry.trim());
        if (match) {
          changed = true;
          return match.id;
        }
      }
      return entry;
    });
    if (changed) {
      onChange(resolved);
    }
    // Intentionally keyed on `options` only: re-resolve stored strings when the
    // option set changes, without re-running on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options]);

  const value = toDisplayValues<T>(fieldValue, options);
  const commit = (next: (T | string)[]) => {
    // Closed mode: only inventory options are selectable, so drop any free-typed
    // string that does not match an option label (typed text `freeSolo` still
    // lets Enter append). Option objects and label-matching text pass through and
    // normalise to inventory ids.
    const selectable = allowCustom
      ? next
      : next.filter(
          (entry) =>
            typeof entry !== 'string' || options.some((o) => getOptionLabel(o) === entry.trim()),
        );
    onChange(normalizeMultiChange<T>(selectable, options, getOptionLabel));
  };

  return (
    <Autocomplete<T | string, true, false, true>
      multiple
      freeSolo
      options={options as (T | string)[]}
      value={value}
      disabled={disabled}
      loading={loading}
      forcePopupIcon
      clearOnBlur
      selectOnFocus
      handleHomeEndKeys
      getOptionLabel={labelOf}
      isOptionEqualToValue={isOptionEqualToValue}
      noOptionsText={noOptionsText}
      onOpen={onOpen}
      data-testid={`${field.name}-autocomplete`}
      filterOptions={(opts, params) => {
        const filtered = filter(opts, params);
        if (!allowCustom) {
          return filtered;
        }
        const input = params.inputValue.trim();
        // Offer the typed text as a "create" suggestion unless it already
        // matches an inventory option's label.
        const exists = options.some((o) => getOptionLabel(o) === input);
        if (input !== '' && !exists) {
          filtered.push(input);
        }
        return filtered;
      }}
      renderOption={(props, option) => {
        const { key, ...rest } = props as {
          key?: string;
        } & React.HTMLAttributes<HTMLLIElement>;
        return typeof option === 'string' ? (
          <Box component="li" key={key} {...rest} sx={{ fontStyle: 'italic' }}>
            <em>{option}</em>
          </Box>
        ) : (
          <Box component="li" key={key} {...rest}>
            {getOptionLabel(option)}
          </Box>
        );
      }}
      renderTags={(tagValues, getTagProps) =>
        tagValues.map((option, index) => {
          const { key, ...tagProps } = getTagProps({ index });
          const custom = typeof option === 'string';
          return (
            <Chip
              key={key}
              label={custom ? <em>{labelOf(option)}</em> : labelOf(option)}
              size="small"
              {...tagProps}
            />
          );
        })
      }
      onChange={(_event, next) => commit(next)}
      renderInput={(params) => (
        <TextField
          {...params}
          inputRef={field.ref}
          onBlur={field.onBlur}
          label={label}
          required={required}
          error={error || !!fieldError}
          helperText={fieldError ? fieldError.message : helperText}
          size="small"
          InputProps={{
            ...params.InputProps,
            endAdornment: (
              <>
                {loading ? <CircularProgress color="inherit" size={20} /> : null}
                {params.InputProps.endAdornment}
              </>
            ),
          }}
        />
      )}
    />
  );
}

/**
 * Multi-value reference selector: one MUI Autocomplete (`multiple` + `freeSolo`)
 * that commits a `(number | string)[]` to react-hook-form. Picking inventory
 * options commits their **ids**; when `allowCustom`, typing novel values commits
 * the **strings** (rendered as italic chips); clearing commits `[]`.
 *
 * With `allowCustom={false}` it is a closed multi-select combobox: only
 * inventory options are selectable (no "create" suggestion, typed text not
 * committed). One component serves both cases, mirroring how `FreeSoloSelect`
 * unifies the single-value picker.
 */
export function FreeSoloMultiSelect<T extends MultiReferenceOption>({
  name,
  required,
  label,
  ...rest
}: FreeSoloMultiSelectProps<T>) {
  const { control } = useFormContext();

  return (
    <Controller
      name={name}
      control={control}
      defaultValue={[]}
      rules={
        required
          ? {
              validate: (value: unknown) =>
                (Array.isArray(value) && value.length > 0) || `${label} is required`,
            }
          : undefined
      }
      render={({ field, fieldState: { error: fieldError } }) => (
        <FreeSoloMultiAutocomplete<T>
          field={field}
          fieldError={fieldError}
          label={label}
          required={required}
          {...rest}
        />
      )}
    />
  );
}
