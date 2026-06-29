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

import { useEffect } from 'react';
import { Controller, useFormContext } from 'react-hook-form';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import TextField from '@mui/material/TextField';
import { useServices, type ServiceOption, type ServiceType } from '../../hooks/useServices';
import { extractId } from '../../utils/extractId';
import { isHydratedReferenceOption, resolveReferenceOption } from '../../utils/referenceOption';
import { FreeSoloSelect } from '../FreeSoloSelect';

const EMPTY_OPTIONS: ServiceOption[] = [];

export interface ServiceSelectorProps {
  /**
   * react-hook-form field name. Without `allowCustom`, stores a
   * `ServiceOption | null`; with `allowCustom`, stores the committed
   * `number | string | null` (inventory id, free-typed value, or unset).
   */
  name: string;
  label: string;
  required?: boolean;
  /** Optional filter — only services whose `type` is in this list are shown. */
  serviceTypes?: readonly ServiceType[];
  disabled?: boolean;
  helperText?: string;
  /** Offer free-text (free-solo) entry alongside the inventory options. */
  allowCustom?: boolean;
}

const getOptionLabel = (opt: ServiceOption | string) =>
  typeof opt === 'string' ? opt : `${opt.name} (${opt.type})`;
// Used by the free-solo path. Because the label is `name (type)`, the
// typed-text-to-id resolution only fires if the user types that exact form;
// in practice a free-typed service almost always commits as a custom string,
// while inventory picks resolve to an id through the option-click path.
const getServiceOptionLabel = (opt: ServiceOption) => `${opt.name} (${opt.type})`;

const isOptionEqualToValue = (a: ServiceOption, b: ServiceOption) => a.id === b.id;

interface InventoryServiceAutocompleteProps {
  name: string;
  label: string;
  required?: boolean;
  services: readonly ServiceOption[];
  isLoading: boolean;
  isError: boolean;
  disabled?: boolean;
  helperText?: string;
}

/**
 * Inventory-only service picker. Hydrates persisted scalar ids from
 * ``data['_form']`` into ``ServiceOption`` objects once services load so edit
 * forms show ``name (type)`` instead of ``undefined (undefined)``.
 */
function InventoryServiceAutocomplete({
  name,
  label,
  required,
  services,
  isLoading,
  isError,
  disabled,
  helperText,
}: InventoryServiceAutocompleteProps) {
  const { control, setValue, watch } = useFormContext();
  const storedValue = watch(name);

  useEffect(() => {
    if (isHydratedReferenceOption(storedValue)) {
      return;
    }
    const id = extractId(storedValue);
    if (id === null) {
      return;
    }
    const match = services.find((service) => service.id === id);
    if (match) {
      setValue(name, match, { shouldDirty: false, shouldValidate: false });
    }
  }, [storedValue, services, name, setValue]);

  return (
    <Controller
      name={name}
      control={control}
      rules={required ? { required: `${label} is required` } : undefined}
      render={({ field, fieldState: { error: fieldError } }) => (
        <Autocomplete<ServiceOption, false, false, false>
          value={resolveReferenceOption(field.value, services)}
          onChange={(_event, next) => field.onChange(next)}
          onBlur={field.onBlur}
          options={services as ServiceOption[]}
          loading={isLoading}
          disabled={disabled || isError}
          getOptionLabel={getOptionLabel}
          isOptionEqualToValue={isOptionEqualToValue}
          noOptionsText={isLoading ? 'Loading services…' : 'No services available'}
          data-testid={`${name}-autocomplete`}
          renderInput={(params) => (
            <TextField
              {...params}
              inputRef={field.ref}
              label={label}
              required={required}
              error={isError || !!fieldError}
              helperText={fieldError?.message ?? helperText}
              size="small"
              InputProps={{
                ...params.InputProps,
                endAdornment: (
                  <>
                    {isLoading ? <CircularProgress color="inherit" size={20} /> : null}
                    {params.InputProps.endAdornment}
                  </>
                ),
              }}
            />
          )}
          renderOption={(props, option) => {
            const { key, ...rest } = props as {
              key?: string;
            } & React.HTMLAttributes<HTMLLIElement>;
            return (
              <Box component="li" key={key} {...rest}>
                {getOptionLabel(option)}
              </Box>
            );
          }}
        />
      )}
    />
  );
}

export function ServiceSelector({
  name,
  label,
  required,
  serviceTypes,
  disabled,
  helperText,
  allowCustom,
}: ServiceSelectorProps) {
  const {
    data: services = EMPTY_OPTIONS,
    isLoading,
    isError,
    error,
  } = useServices({ serviceTypes });

  const empty = !isLoading && !isError && services.length === 0;

  const text = isError
    ? (error?.message ?? 'Failed to load services')
    : empty
      ? 'No services available'
      : helperText;

  if (allowCustom) {
    return (
      <FreeSoloSelect<ServiceOption>
        name={name}
        label={label}
        options={services}
        getOptionLabel={getServiceOptionLabel}
        required={required}
        disabled={disabled || isError}
        loading={isLoading}
        helperText={text}
        error={isError}
        noOptionsText={isLoading ? 'Loading services…' : 'No services available'}
      />
    );
  }

  return (
    <InventoryServiceAutocomplete
      name={name}
      label={label}
      required={required}
      services={services}
      isLoading={isLoading}
      isError={isError}
      disabled={disabled}
      helperText={text}
    />
  );
}
