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

import { useFormContext } from 'react-hook-form';
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
  disabled,
  helperText,
}: ServiceSelectorProps) {
  const { control } = useFormContext();

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
        noOptionsText: isLoading ? 'Loading services…' : 'No services available',
      }}
      textFieldProps={{ helperText: text, error: isError }}
    />
  );
}
