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
import { useSnackbar } from 'notistack';
import { useHosts, type HostOption } from '../../hooks/useHosts';
import { useServices, type ServiceOption } from '../../hooks/useServices';
import { extractId } from '../../utils/extractId';
import { FreeSoloMultiSelect } from '../FreeSoloMultiSelect';
import { resolveExecutorHostForService } from './resolveExecutorHostForService';

const EMPTY_HOSTS: HostOption[] = [];
const EMPTY_SERVICES: ServiceOption[] = [];

export interface HostSelectorProps {
  /**
   * react-hook-form field name. In single mode stores a `HostOption | null`;
   * in `multiple` mode stores a `(number | string)[]` (selected host ids).
   */
  name: string;
  label: string;
  required?: boolean;
  disabled?: boolean;
  helperText?: string;
  /**
   * Optional upstream service field. When set, the selector clears on service
   * change and auto-selects an executor using Dipper's resolve order
   * (node name → address → service name). The user may still override.
   */
  dependsOn?: string;
  /**
   * Render a closed multi-value host selector committing a `(number | string)[]`.
   * Host free-solo is not offered, so multi-host is always a closed combobox.
   * Cascade auto-select applies to single mode only.
   */
  multiple?: boolean;
}

const getOptionLabel = (opt: HostOption | string) => (typeof opt === 'string' ? opt : opt.name);
const getHostOptionLabel = (opt: HostOption) => opt.name;

const isOptionEqualToValue = (a: HostOption, b: HostOption) => a.id === b.id;

function hostValueId(value: unknown): string | undefined {
  if (value && typeof value === 'object' && 'id' in value) {
    const id = (value as { id: unknown }).id;
    return typeof id === 'string' || typeof id === 'number' ? String(id) : undefined;
  }
  if (typeof value === 'string' && value !== '') {
    return value;
  }
  return undefined;
}

function parentResetKey(parent: unknown): string {
  if (parent && typeof parent === 'object' && 'id' in parent) {
    const id = (parent as { id: unknown }).id;
    return `id:${id ?? 'none'}`;
  }
  if (typeof parent === 'number' && Number.isFinite(parent)) {
    return `id:${parent}`;
  }
  if (typeof parent === 'string' && parent.trim() !== '') {
    return /^\d+$/.test(parent.trim()) ? `id:${parent.trim()}` : `custom:${parent.trim()}`;
  }
  return 'id:none';
}

export function HostSelector({
  name,
  label,
  required,
  disabled,
  helperText,
  dependsOn,
  multiple,
}: HostSelectorProps) {
  const {
    control,
    formState: { errors },
    setValue,
    getValues,
  } = useFormContext();
  const { enqueueSnackbar } = useSnackbar();

  const { data, isLoading, isError, error, refetch } = useHosts();
  const hosts = data ?? EMPTY_HOSTS;

  const { data: services = EMPTY_SERVICES } = useServices({
    enabled: Boolean(dependsOn) && !multiple,
  });

  const parent = useWatch({
    control,
    name: dependsOn ?? '',
    disabled: !dependsOn || Boolean(multiple),
  }) as ServiceOption | number | string | null | undefined;

  const resetKey = dependsOn && !multiple ? parentResetKey(parent) : 'id:none';
  const prevParentKeyRef = useRef<string | undefined>(undefined);
  const autoHostIdRef = useRef<string | undefined>(undefined);

  // Cascade: on upstream service change, clear the host; then auto-select when
  // a Dipper-order match exists and the field is empty or still holds the
  // previous auto value (so a manual override is preserved).
  useEffect(() => {
    if (!dependsOn || multiple) {
      return;
    }

    if (prevParentKeyRef.current === undefined) {
      prevParentKeyRef.current = resetKey;
    } else if (prevParentKeyRef.current !== resetKey) {
      prevParentKeyRef.current = resetKey;
      setValue(name, null, { shouldDirty: false, shouldValidate: false });
      autoHostIdRef.current = undefined;
    }

    const serviceId = extractId(parent);
    const service: ServiceOption | undefined =
      parent && typeof parent === 'object' && 'name' in parent
        ? (parent as ServiceOption)
        : serviceId !== null
          ? services.find((svc) => svc.id === serviceId)
          : undefined;

    if (!service || hosts.length === 0) {
      return;
    }

    const match = resolveExecutorHostForService(hosts, service);
    if (!match) {
      return;
    }

    const currentId = hostValueId(getValues(name));
    if (currentId === undefined || currentId === '' || currentId === autoHostIdRef.current) {
      setValue(name, match, { shouldDirty: false, shouldValidate: false });
      autoHostIdRef.current = match.id;
    }
  }, [dependsOn, multiple, resetKey, parent, services, hosts, name, setValue, getValues]);

  const empty = !isLoading && !isError && hosts.length === 0;

  const fieldError = errors[name]?.message as string | undefined;

  // Surface a hosts-query failure (e.g. an upstream Tasks-API 502) via the
  // shell's snackbar. React Query keeps the `error` object identity stable
  // between renders until the next refetch, so de-dup on that identity to
  // raise the snackbar once per failure rather than once per render.
  const lastSurfacedRef = useRef<unknown>(null);
  useEffect(() => {
    if (isError && error && error !== lastSurfacedRef.current) {
      enqueueSnackbar(`Failed to load executor hosts: ${error.message}`, {
        variant: 'error',
        autoHideDuration: 30_000,
      });
      lastSurfacedRef.current = error;
    }
  }, [isError, error, enqueueSnackbar]);

  let text = helperText;
  if (fieldError) {
    text = fieldError;
  } else if (isError) {
    text = error?.message ?? 'Failed to load hosts';
  } else if (empty) {
    text = 'No hosts available';
  }

  if (multiple) {
    return (
      <FreeSoloMultiSelect<HostOption>
        name={name}
        label={label}
        options={hosts}
        getOptionLabel={getHostOptionLabel}
        allowCustom={false}
        required={required}
        disabled={disabled || isError}
        loading={isLoading}
        helperText={text}
        error={isError || !!fieldError}
        noOptionsText={isLoading ? 'Loading hosts…' : 'No hosts available'}
      />
    );
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
        onOpen: () => refetch(),
      }}
      textFieldProps={{ helperText: text, error: isError || !!fieldError }}
    />
  );
}
