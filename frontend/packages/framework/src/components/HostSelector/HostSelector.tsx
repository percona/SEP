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

import { Alert } from '@mui/material';
import { useEffect, useRef, type ReactNode } from 'react';
import { get, useFormContext, useWatch } from 'react-hook-form';
import { AutoCompleteInput } from '@percona/percona-ui';
import { useSnackbar } from 'notistack';
import { useHosts, type HostOption } from '../../hooks/useHosts';
import { useResolvedServiceField } from '../../hooks/useResolvedServiceField';
import type { ServiceType } from '../../hooks/useServices';
import { FreeSoloMultiSelect } from '../FreeSoloMultiSelect';
import { FreeSoloSelect } from '../FreeSoloSelect';
import { isHostMismatch } from './isHostMismatch';
import { resolveExecutorHostForService } from './resolveExecutorHostForService';

const EMPTY_HOSTS: HostOption[] = [];

export interface HostSelectorProps {
  /**
   * react-hook-form field name. Without `allowCustom`, stores a
   * `HostOption | null`; with `allowCustom`, stores the committed
   * `string | null` (executor id, free-typed value, or unset). In `multiple`
   * mode stores a `(number | string)[]` (selected host ids and/or free-typed
   * values).
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
   * Cascade auto-select applies to single mode only.
   */
  dependsOn?: string;
  /**
   * Service field for the non-blocking co-location warning. Independent of
   * ``dependsOn``. Single-value only — multi-value host fields ignore this.
   */
  targetService?: string;
  /**
   * When resolving a scalar ``dependsOn`` id, bound the services fetch to these
   * types (typically the parent ``ServiceField.service_types``). Omit only when
   * the parent value is already a hydrated ``ServiceOption``; an unbound
   * ``useServices()`` page-loop is intentionally not used here.
   */
  serviceTypes?: readonly ServiceType[];
  /** Offer free-text (free-solo) entry alongside the inventory options. */
  allowCustom?: boolean;
  /**
   * Render a multi-value host selector committing a `(number | string)[]`.
   * Combined with `allowCustom`, yields a free-solo multi-select; otherwise a
   * closed multi-select combobox. Cascade auto-select applies to single mode
   * only.
   */
  multiple?: boolean;
}

const getOptionLabel = (opt: HostOption | string) => {
  if (typeof opt === 'string') {
    return opt;
  }
  return opt.name;
};

const getHostOptionLabel = (opt: HostOption) => opt.name;

const isOptionEqualToValue = (a: HostOption, b: HostOption) => a.id === b.id;

function hostValueId(value: unknown): string | undefined {
  if (typeof value === 'string' && value !== '') {
    return value;
  }
  if (!value || typeof value !== 'object' || !('id' in value)) {
    return undefined;
  }
  const id = (value as { id: unknown }).id;
  if (typeof id === 'string') {
    return id;
  }
  if (typeof id === 'number') {
    return String(id);
  }
  return undefined;
}

function resolveHelperText({
  helperText,
  fieldError,
  isError,
  errorMessage,
  empty,
}: {
  helperText?: string;
  fieldError?: string;
  isError: boolean;
  errorMessage?: string;
  empty: boolean;
}): string | undefined {
  if (fieldError) {
    return fieldError;
  }
  if (isError && errorMessage) {
    return errorMessage;
  }
  if (isError) {
    return 'Failed to load hosts';
  }
  if (empty) {
    return 'No hosts available';
  }
  return helperText;
}

function cascadeCommitValue(match: HostOption, allowCustom: boolean): HostOption | string {
  if (allowCustom) {
    return match.id;
  }
  return match;
}

/**
 * Cascade auto-select for a single host field. Mounted only when ``dependsOn``
 * is set. Scalar parent ids rehydrate through {@link useResolvedServiceField}
 * (same path as task-name suggestion and other service consumers).
 *
 * When ``allowCustom`` is set the free-solo path stores a scalar id/string, so
 * cascade commits ``match.id``; otherwise it commits the hydrated
 * ``HostOption`` expected by the closed ``AutoCompleteInput``.
 */
function HostServiceCascade({
  name,
  dependsOn,
  hosts,
  serviceTypes,
  allowCustom,
}: {
  name: string;
  dependsOn: string;
  hosts: HostOption[];
  serviceTypes?: readonly ServiceType[];
  allowCustom: boolean;
}) {
  const { setValue, getValues } = useFormContext();
  const { service, resetKey } = useResolvedServiceField(dependsOn, serviceTypes);
  const prevParentKeyRef = useRef<string | undefined>(undefined);
  const autoHostIdRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    const previousKey = prevParentKeyRef.current;
    prevParentKeyRef.current = resetKey;

    if (previousKey !== undefined && previousKey !== resetKey) {
      setValue(name, null, { shouldDirty: false, shouldValidate: false });
      autoHostIdRef.current = undefined;
    }

    if (!service) {
      return;
    }
    if (hosts.length === 0) {
      return;
    }

    const match = resolveExecutorHostForService(hosts, service);
    if (!match) {
      return;
    }

    const currentId = hostValueId(getValues(name));
    const userOverrodeAutoPick = currentId !== undefined && currentId !== autoHostIdRef.current;
    if (userOverrodeAutoPick) {
      return;
    }

    setValue(name, cascadeCommitValue(match, allowCustom), {
      shouldDirty: false,
      shouldValidate: false,
    });
    autoHostIdRef.current = match.id;
  }, [resetKey, service, hosts, name, setValue, getValues, allowCustom]);

  return null;
}

/**
 * Non-blocking co-location warning for a single host field. Mounted only when
 * ``targetService`` is set. Compares the selected host's network address
 * against the resolved service's node address; stays silent whenever either
 * side cannot be established.
 */
function HostMismatchWarning({
  name,
  targetService,
  hosts,
  hostsLoading,
  hostsError,
  fieldError,
}: {
  name: string;
  targetService: string;
  hosts: HostOption[];
  hostsLoading: boolean;
  hostsError: boolean;
  fieldError?: string;
}) {
  const hostValue = useWatch({ name });
  // Resolve types from the target service field, not cascade ``serviceTypes``
  // (those are scoped to ``dependsOn``, which may name a different field).
  const { service, isResolving, isError: serviceError } = useResolvedServiceField(targetService);

  if (fieldError) {
    return null;
  }
  if (hostsLoading || hostsError || isResolving || serviceError) {
    return null;
  }
  if (!service) {
    return null;
  }

  const hostId = hostValueId(hostValue);
  if (!hostId) {
    return null;
  }

  const selectedHost = hosts.find((host) => host.id === hostId);
  if (!selectedHost) {
    return null;
  }

  const serviceNodeAddress = service.node?.address;
  if (!isHostMismatch(selectedHost.address, serviceNodeAddress)) {
    return null;
  }

  return (
    <Alert severity="warning" sx={{ mt: 1 }}>
      The selected executor host ({selectedHost.name}, {selectedHost.address}) is not the node where{' '}
      {service.name} runs ({serviceNodeAddress}).
    </Alert>
  );
}

export function HostSelector({
  name,
  label,
  required,
  disabled,
  helperText,
  dependsOn,
  targetService,
  serviceTypes,
  allowCustom,
  multiple,
}: HostSelectorProps) {
  const {
    control,
    formState: { errors },
  } = useFormContext();
  const { enqueueSnackbar } = useSnackbar();

  const { data, isLoading, isError, error, refetch } = useHosts();
  const hosts = data ?? EMPTY_HOSTS;
  const empty = !isLoading && !isError && hosts.length === 0;
  // Path-aware: a one-of branch field carries a dotted name (`source.host`),
  // which `errors[name]` would never resolve.
  const fieldError = get(errors, name)?.message as string | undefined;
  const freeSolo = Boolean(allowCustom);
  // A failed hosts query does not disable the control: `onOpen` holds the only
  // `refetch()` trigger and a disabled Autocomplete never opens, so one failure
  // would wedge the field until the page remounts. The error stays visible
  // through `text` / `showError` / the snackbar. Same reasoning as
  // StandaloneHostSelector.
  const inputDisabled = Boolean(disabled);
  const showError = isError || Boolean(fieldError);
  const text = resolveHelperText({
    helperText,
    fieldError,
    isError,
    errorMessage: error?.message,
    empty,
  });

  let noOptionsText = 'No hosts available';
  if (isLoading) {
    noOptionsText = 'Loading hosts…';
  }

  let requiredRules: { required: string } | undefined;
  if (required) {
    requiredRules = { required: `${label} is required` };
  }

  // Surface a hosts-query failure (e.g. an upstream Tasks-API 502) via the
  // shell's snackbar. React Query keeps the `error` object identity stable
  // between renders until the next refetch, so de-dup on that identity to
  // raise the snackbar once per failure rather than once per render.
  const lastSurfacedRef = useRef<unknown>(null);
  useEffect(() => {
    if (!isError || !error) {
      return;
    }
    if (error === lastSurfacedRef.current) {
      return;
    }
    enqueueSnackbar(`Failed to load executor hosts: ${error.message}`, {
      variant: 'error',
      autoHideDuration: 30_000,
    });
    lastSurfacedRef.current = error;
  }, [isError, error, enqueueSnackbar]);

  if (multiple) {
    return (
      <FreeSoloMultiSelect<HostOption>
        name={name}
        label={label}
        options={hosts}
        getOptionLabel={getHostOptionLabel}
        allowCustom={freeSolo}
        required={required}
        disabled={inputDisabled}
        loading={isLoading}
        helperText={text}
        error={showError}
        noOptionsText={noOptionsText}
        onOpen={() => {
          void refetch();
        }}
      />
    );
  }

  let cascade: ReactNode = null;
  if (dependsOn) {
    cascade = (
      <HostServiceCascade
        name={name}
        dependsOn={dependsOn}
        hosts={hosts}
        serviceTypes={serviceTypes}
        allowCustom={freeSolo}
      />
    );
  }

  let mismatchWarning: ReactNode = null;
  if (targetService) {
    mismatchWarning = (
      <HostMismatchWarning
        name={name}
        targetService={targetService}
        hosts={hosts}
        hostsLoading={isLoading}
        hostsError={isError}
        fieldError={fieldError}
      />
    );
  }

  if (freeSolo) {
    return (
      <>
        {cascade}
        <FreeSoloSelect<HostOption>
          name={name}
          label={label}
          options={hosts}
          getOptionLabel={getHostOptionLabel}
          required={required}
          disabled={inputDisabled}
          loading={isLoading}
          helperText={text}
          error={showError}
          noOptionsText={noOptionsText}
          onOpen={() => {
            void refetch();
          }}
        />
        {mismatchWarning}
      </>
    );
  }

  return (
    <>
      {cascade}
      <AutoCompleteInput<HostOption>
        name={name}
        label={label}
        control={control}
        isRequired={required}
        loading={isLoading}
        disabled={inputDisabled}
        options={hosts}
        controllerProps={{
          name,
          rules: requiredRules,
        }}
        autoCompleteProps={{
          getOptionLabel,
          isOptionEqualToValue,
          noOptionsText,
          onOpen: () => refetch(),
        }}
        textFieldProps={{ helperText: text, error: showError }}
      />
      {mismatchWarning}
    </>
  );
}
