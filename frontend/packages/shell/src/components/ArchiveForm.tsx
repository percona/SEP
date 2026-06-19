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

import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useFormContext, useWatch } from 'react-hook-form';
import Box from '@mui/material/Box';
import Checkbox from '@mui/material/Checkbox';
import FormControlLabel from '@mui/material/FormControlLabel';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import {
  SchemaFormRenderer,
  ServiceSelector,
  useSchemas,
  useTables,
  type PluginFormSlotProps,
  type RenderFieldArgs,
  type ServiceType,
} from '@sep/framework';
import { ArchiveSchemaCombo, type ArchiveComboOption } from './ArchiveSchemaCombo';

/** Source mode: pick a schema + table, or write a custom query. */
type SourceMode = 'schema' | 'query';

// Source-section wire field names (must match app/sep/plugins/archives/schema.py).
const SERVICE_ID = 'service_id';
const SOURCE_DB_ID = 'source_db_id';
const SOURCE_DB_NAME = 'source_db_name';
const SOURCE_TABLE_ID = 'source_table_id';
const SOURCE_TABLE_NAME = 'source_table_name';
const SOURCE_QUERY = 'source_query';

const SOURCE_FIELD_NAMES = new Set([
  SOURCE_DB_ID,
  SOURCE_DB_NAME,
  SOURCE_TABLE_ID,
  SOURCE_TABLE_NAME,
  SOURCE_QUERY,
]);

// Destination-section wire field names (must match app/sep/plugins/archives/schema.py).
const DEST_TABLE_ID = 'dest_table_id';
const DEST_TABLE_NAME = 'dest_table_name';
const DEST_FILE = 'dest_file';
const DEST_SERVICE_ID = 'dest_service_id';
const DEST_HOST = 'dest_host';
const DEST_PORT = 'dest_port';
const DEST_DB_ID = 'dest_db_id';
const DEST_DB_NAME = 'dest_db_name';

// Folded into ArchiveDestinationFields (the Destination-section block). The
// schema (dest_db_*) pair is relocated here out of the Destination Host section.
const DEST_FOLDED_FIELD_NAMES = new Set([DEST_TABLE_NAME, DEST_FILE, DEST_DB_ID, DEST_DB_NAME]);
// Folded into ArchiveDestinationHostFields (the Destination Host block).
const DEST_HOST_FOLDED_FIELD_NAMES = new Set([DEST_HOST, DEST_PORT]);

/** Destination mode: archive into a schema + table, or into a file. */
type DestMode = 'table' | 'file';
/** Within the "Use a different host?" opt-in: inventory service vs manual host. */
type HostMode = 'service' | 'manual';

/** Resolve an id-or-option form value down to a numeric inventory id, or null. */
function resolveId(value: unknown): number | null {
  if (value && typeof value === 'object' && 'id' in (value as Record<string, unknown>)) {
    const id = (value as { id: unknown }).id;
    return typeof id === 'number' ? id : null;
  }
  return typeof value === 'number' ? value : null;
}

/** True when a wire id field currently holds an inventory pick (option / raw id). */
function isInventoryId(value: unknown): boolean {
  return resolveId(value) !== null;
}

/**
 * The inventory name for an id value, or null when it cannot be resolved.
 * An option object carries its own name; a raw id (edit prefill) is looked up
 * in the loaded options. Returning null (rather than stringifying the id) keeps
 * a bogus numeric "name" out of the payload — the id is left intact instead.
 */
function resolveName(value: unknown, options: ArchiveComboOption[]): string | null {
  if (value && typeof value === 'object' && 'name' in (value as Record<string, unknown>)) {
    return String((value as { name: unknown }).name);
  }
  if (typeof value === 'number') {
    return options.find((o) => o.id === value)?.name ?? null;
  }
  return null;
}

interface SourceModeToggleProps {
  mode: SourceMode;
  onChange: (mode: SourceMode) => void;
}

/**
 * Explicit Schema + Table vs Source Query selector. On switch it clears the
 * inactive mode's wire fields so a submission never carries both branches —
 * replacing the old silent show/hide on `source_query`.
 */
function SourceModeToggle({ mode, onChange }: SourceModeToggleProps) {
  const { setValue } = useFormContext();

  const handleChange = (_event: unknown, next: SourceMode | null) => {
    if (!next || next === mode) {
      return;
    }
    const clearOpts = { shouldDirty: true, shouldValidate: true };
    if (next === 'query') {
      setValue(SOURCE_DB_ID, '', clearOpts);
      setValue(SOURCE_DB_NAME, '', clearOpts);
      setValue(SOURCE_TABLE_ID, '', clearOpts);
      setValue(SOURCE_TABLE_NAME, '', clearOpts);
    } else {
      setValue(SOURCE_QUERY, '', clearOpts);
    }
    onChange(next);
  };

  return (
    <Box sx={{ mb: 1 }}>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={mode}
        onChange={handleChange}
        aria-label="Source mode"
      >
        <ToggleButton value="schema">Schema + Table</ToggleButton>
        <ToggleButton value="query">Source Query</ToggleButton>
      </ToggleButtonGroup>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        {mode === 'schema'
          ? 'Select or type a source schema and table. Picks come from inventory; typed values are sent as names.'
          : 'Define the source rows with a custom query instead of a schema and table.'}
      </Typography>
    </Box>
  );
}

interface ArchiveSourceFieldsProps {
  mode: SourceMode;
  onModeChange: (mode: SourceMode) => void;
}

/**
 * The whole Source section body. Rendered once (anchored on the first visible
 * source field for the active mode) and owns the toggle plus the mode-specific
 * inputs, so the schema / table combos and the query box never appear together.
 *
 * Exported for unit testing of the cascade / normalisation effects.
 */
export function ArchiveSourceFields({ mode, onModeChange }: ArchiveSourceFieldsProps) {
  const { control, register, setValue } = useFormContext();

  const schemaIdValue = useWatch({ control, name: SOURCE_DB_ID });
  const tableIdValue = useWatch({ control, name: SOURCE_TABLE_ID });
  const schemaNameValue = useWatch({ control, name: SOURCE_DB_NAME }) as string | undefined;
  const tableNameValue = useWatch({ control, name: SOURCE_TABLE_NAME }) as string | undefined;

  const serviceId = resolveId(useWatch({ control, name: SERVICE_ID }));
  const schemaId = resolveId(schemaIdValue);

  // Only the schema mode shows the combos, so skip the inventory fetches in
  // query mode (the component still mounts there to host the toggle).
  const enabled = mode === 'schema';
  const { data: schemas = [], isLoading: schemasLoading } = useSchemas({ serviceId, enabled });
  const { data: tables = [], isLoading: tablesLoading } = useTables({ schemaId, enabled });

  const clearOpts = { shouldDirty: true, shouldValidate: true };

  // Cascade: changing the source service invalidates the picked schema and
  // table, so clear all four. Skip the initial render (and edit prefill) by
  // seeding the ref with the mounted value.
  const prevServiceId = useRef(serviceId);
  useEffect(() => {
    if (prevServiceId.current !== serviceId) {
      prevServiceId.current = serviceId;
      setValue(SOURCE_DB_ID, '', clearOpts);
      setValue(SOURCE_DB_NAME, '', clearOpts);
      setValue(SOURCE_TABLE_ID, '', clearOpts);
      setValue(SOURCE_TABLE_NAME, '', clearOpts);
    }
    // clearOpts is a stable literal; setValue is stable from RHF.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serviceId, setValue]);

  // Cascade: picking a *different* inventory schema invalidates the picked
  // table. Only fire on a transition to a new non-null id so the id→name
  // normalisation below (which nulls the id) does not wipe a just-typed table.
  const prevSchemaId = useRef(schemaId);
  useEffect(() => {
    if (prevSchemaId.current !== schemaId && schemaId !== null) {
      setValue(SOURCE_TABLE_ID, '', clearOpts);
      setValue(SOURCE_TABLE_NAME, '', clearOpts);
    }
    prevSchemaId.current = schemaId;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schemaId, setValue]);

  // Keep the schema/table pair on one side of the wire contract: validator 5a
  // accepts both ids or both names, never a mix. As soon as either side is a
  // manual name, downgrade an inventory pick on the other side to its name so
  // the submission stays valid (the schema/table identity is unchanged).
  useEffect(() => {
    const anyName = Boolean(schemaNameValue) || Boolean(tableNameValue);
    if (!anyName) {
      return;
    }
    // Only downgrade when the real name is known; otherwise leave the id and let
    // validation surface the mix (avoids writing a numeric id as a "name").
    if (isInventoryId(schemaIdValue)) {
      const name = resolveName(schemaIdValue, schemas);
      if (name !== null) {
        setValue(SOURCE_DB_NAME, name, clearOpts);
        setValue(SOURCE_DB_ID, '', clearOpts);
      }
    }
    if (isInventoryId(tableIdValue)) {
      const name = resolveName(tableIdValue, tables);
      if (name !== null) {
        setValue(SOURCE_TABLE_NAME, name, clearOpts);
        setValue(SOURCE_TABLE_ID, '', clearOpts);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schemaIdValue, tableIdValue, schemaNameValue, tableNameValue, schemas, tables, setValue]);

  return (
    <Box>
      <SourceModeToggle mode={mode} onChange={onModeChange} />

      {mode === 'schema' ? (
        <>
          <Box sx={{ mb: 2 }}>
            <ArchiveSchemaCombo
              idFieldName={SOURCE_DB_ID}
              nameFieldName={SOURCE_DB_NAME}
              label="Source Schema"
              options={schemas}
              loading={schemasLoading}
              helperText={
                serviceId === null
                  ? 'Select a source service to list its schemas, or type a name.'
                  : 'Pick a schema from inventory or type a new one.'
              }
            />
          </Box>
          <Box sx={{ mb: 2 }}>
            <ArchiveSchemaCombo
              idFieldName={SOURCE_TABLE_ID}
              nameFieldName={SOURCE_TABLE_NAME}
              label="Source Table"
              options={tables}
              loading={tablesLoading}
              helperText={
                schemaId !== null
                  ? 'Pick a table from inventory or type a new one.'
                  : schemaNameValue
                    ? 'Type a table name (the schema is not from inventory).'
                    : 'Choose or type a source schema first, or type a table name.'
              }
            />
          </Box>
        </>
      ) : (
        <Box sx={{ mb: 2 }}>
          <TextField
            {...register(SOURCE_QUERY)}
            label="Source Query"
            fullWidth
            multiline
            minRows={2}
            helperText="Custom query defining the source rows; mutually exclusive with Source Schema/Table."
          />
        </Box>
      )}
    </Box>
  );
}

interface DestModeToggleProps {
  mode: DestMode;
  onChange: (mode: DestMode) => void;
}

/**
 * Explicit Schema + Table vs Destination File selector. On switch it clears the
 * inactive mode's wire fields so a submission never carries both branches —
 * keeping the backend `CardinalityRule(max=1)` over
 * dest_file / dest_table_id / dest_table_name satisfied.
 */
function DestModeToggle({ mode, onChange }: DestModeToggleProps) {
  const { setValue } = useFormContext();

  const handleChange = (_event: unknown, next: DestMode | null) => {
    if (!next || next === mode) {
      return;
    }
    const clearOpts = { shouldDirty: true, shouldValidate: true };
    if (next === 'file') {
      setValue(DEST_DB_ID, '', clearOpts);
      setValue(DEST_DB_NAME, '', clearOpts);
      setValue(DEST_TABLE_ID, '', clearOpts);
      setValue(DEST_TABLE_NAME, '', clearOpts);
    } else {
      setValue(DEST_FILE, '', clearOpts);
    }
    onChange(next);
  };

  return (
    <Box sx={{ mb: 1 }}>
      <ToggleButtonGroup
        exclusive
        size="small"
        value={mode}
        onChange={handleChange}
        aria-label="Destination mode"
      >
        <ToggleButton value="table">Schema + Table</ToggleButton>
        <ToggleButton value="file">Destination File</ToggleButton>
      </ToggleButtonGroup>
      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
        {mode === 'table'
          ? 'Archive into a destination schema and table. Picks come from inventory; typed values are sent as names.'
          : 'Archive rows into a file on the executor host instead of a destination table.'}
      </Typography>
    </Box>
  );
}

interface ArchiveDestinationFieldsProps {
  mode: DestMode;
  onModeChange: (mode: DestMode) => void;
}

/**
 * The Destination-section body. Owns the Schema + Table vs File toggle and,
 * in table mode, the unified destination schema and table combos. The schema
 * combo (dest_db_id / dest_db_name) is relocated here from the Destination Host
 * section per the redesign; its inventory picks resolve only when a destination
 * service is selected (validator 3c), so options come from `dest_service_id`.
 *
 * Exported for unit testing of the cascade effects and the toggle.
 */
export function ArchiveDestinationFields({ mode, onModeChange }: ArchiveDestinationFieldsProps) {
  const { control, register, setValue } = useFormContext();

  const destServiceId = resolveId(useWatch({ control, name: DEST_SERVICE_ID }));
  const schemaIdValue = useWatch({ control, name: DEST_DB_ID });
  const schemaId = resolveId(schemaIdValue);
  const schemaNameValue = useWatch({ control, name: DEST_DB_NAME }) as string | undefined;

  // Only table mode shows the combos, so skip the inventory fetches in file mode.
  const enabled = mode === 'table';
  const { data: schemas = [], isLoading: schemasLoading } = useSchemas({
    serviceId: destServiceId,
    enabled,
  });
  const { data: tables = [], isLoading: tablesLoading } = useTables({ schemaId, enabled });

  const clearOpts = { shouldDirty: true, shouldValidate: true };

  // Cascade: changing the destination service invalidates the picked schema and
  // table (and clears any typed schema name, mirroring the Source section), so a
  // stale inventory id can never outlive its service (validator 3c). Seed the ref
  // with the mounted value to skip the initial render / edit prefill.
  const prevServiceId = useRef(destServiceId);
  useEffect(() => {
    if (prevServiceId.current !== destServiceId) {
      prevServiceId.current = destServiceId;
      setValue(DEST_DB_ID, '', clearOpts);
      setValue(DEST_DB_NAME, '', clearOpts);
      setValue(DEST_TABLE_ID, '', clearOpts);
      setValue(DEST_TABLE_NAME, '', clearOpts);
    }
    // clearOpts is a stable literal; setValue is stable from RHF.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destServiceId, setValue]);

  // Cascade: any post-mount change to the inventory schema id invalidates the
  // picked table — including a transition to null (the schema was cleared or
  // typed over), which would otherwise leave a stale dest_table_id pointing at
  // the old schema's table. Unlike the Source section, the destination has no
  // id<->name normalisation effect that spuriously nulls schemaId, so there is
  // no need to gate on `schemaId !== null` here (and gating would reintroduce
  // the stale-table bug). The destination schema/table pair has no "both ids or
  // both names" coupling validator (the Source section's 5a/5b have no
  // destination analogue — see schema.py validators 3a-3d), so a mixed
  // inventory-schema + typed-table state is wire-legal and needs no downgrade.
  const prevSchemaId = useRef(schemaId);
  useEffect(() => {
    if (prevSchemaId.current !== schemaId) {
      prevSchemaId.current = schemaId;
      setValue(DEST_TABLE_ID, '', clearOpts);
      setValue(DEST_TABLE_NAME, '', clearOpts);
    }
    // clearOpts is a stable literal; setValue is stable from RHF.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schemaId, setValue]);

  return (
    <Box>
      <DestModeToggle mode={mode} onChange={onModeChange} />

      {mode === 'table' ? (
        <>
          {/*
           * Intentional layout inversion (mandated by the acceptance criteria):
           * the destination schema combo lives in the Destination section, above
           * the "Use a different host?" service selector that supplies its
           * inventory options. With no destination service chosen the combo is
           * type-only (validator 3c); the helper text steers the user downward.
           */}
          <Box sx={{ mb: 2 }}>
            <ArchiveSchemaCombo
              idFieldName={DEST_DB_ID}
              nameFieldName={DEST_DB_NAME}
              label="Destination Schema"
              options={schemas}
              loading={schemasLoading}
              helperText={
                destServiceId === null
                  ? 'Type a schema name. To pick from inventory, enable "Use a different host?" and select a destination service.'
                  : 'Pick a schema from inventory or type a new one.'
              }
            />
          </Box>
          <Box sx={{ mb: 2 }}>
            <ArchiveSchemaCombo
              idFieldName={DEST_TABLE_ID}
              nameFieldName={DEST_TABLE_NAME}
              label="Destination Table"
              options={tables}
              loading={tablesLoading}
              emitScalarId
              helperText={
                schemaId !== null
                  ? 'Pick a table from inventory or type a new one.'
                  : schemaNameValue
                    ? 'Type a table name (the schema is not from inventory).'
                    : 'Choose or type a destination schema first, or type a table name.'
              }
            />
          </Box>
        </>
      ) : (
        <Box sx={{ mb: 2 }}>
          <TextField
            {...register(DEST_FILE)}
            label="Destination File"
            fullWidth
            helperText="File path for archiving rows instead of a destination table."
          />
        </Box>
      )}
    </Box>
  );
}

interface ArchiveDestinationHostFieldsProps {
  useDifferentHost: boolean;
  onUseDifferentHostChange: (value: boolean) => void;
  hostMode: HostMode;
  onHostModeChange: (mode: HostMode) => void;
  serviceTypes: readonly ServiceType[];
}

/**
 * The Destination Host body. The destination defaults to the source service; an
 * explicit "Use a different host?" opt-in reveals a mutually-exclusive choice
 * between an inventory service (dest_service_id) and a manual host
 * (dest_host + dest_port). When the opt-in is off, no host fields are sent and
 * the backend falls back to the source service. The Destination Port renders
 * ONLY in the manual-host branch — the backend ignores a typed port when a
 * destination service is selected, so it must not appear there.
 *
 * Exported for unit testing of the opt-in mutual exclusivity and port visibility.
 */
export function ArchiveDestinationHostFields({
  useDifferentHost,
  onUseDifferentHostChange,
  hostMode,
  onHostModeChange,
  serviceTypes,
}: ArchiveDestinationHostFieldsProps) {
  const { register, setValue } = useFormContext();

  const clearOpts = { shouldDirty: true, shouldValidate: true };

  const handleUseDifferentHost = (checked: boolean) => {
    if (!checked) {
      // Opt-out: drop every host field so the backend falls back to the source
      // service. Clearing dest_service_id cascades (in ArchiveDestinationFields)
      // to the relocated destination schema, keeping validator 3c satisfied.
      setValue(DEST_SERVICE_ID, '', clearOpts);
      setValue(DEST_HOST, '', clearOpts);
      setValue(DEST_PORT, '', clearOpts);
    }
    onUseDifferentHostChange(checked);
  };

  const handleHostMode = (_event: unknown, next: HostMode | null) => {
    if (!next || next === hostMode) {
      return;
    }
    if (next === 'service') {
      setValue(DEST_HOST, '', clearOpts);
      setValue(DEST_PORT, '', clearOpts);
    } else {
      // Manual host: no inventory service, so an inventory destination schema
      // can no longer resolve (validator 3c). Clearing it cascades the table too.
      setValue(DEST_SERVICE_ID, '', clearOpts);
    }
    onHostModeChange(next);
  };

  return (
    <Box>
      <FormControlLabel
        control={
          <Checkbox
            checked={useDifferentHost}
            onChange={(event) => handleUseDifferentHost(event.target.checked)}
          />
        }
        label="Use a different host?"
      />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        Off: the destination uses the source service. On: choose a destination service from
        inventory, or enter a host manually.
      </Typography>

      {useDifferentHost && (
        <Box>
          <ToggleButtonGroup
            exclusive
            size="small"
            value={hostMode}
            onChange={handleHostMode}
            aria-label="Destination host mode"
            sx={{ mb: 1 }}
          >
            <ToggleButton value="service">Pick from inventory</ToggleButton>
            <ToggleButton value="manual">Enter host manually</ToggleButton>
          </ToggleButtonGroup>

          {hostMode === 'service' ? (
            <Box sx={{ mb: 2 }}>
              <ServiceSelector
                name={DEST_SERVICE_ID}
                label="Destination Service"
                serviceTypes={serviceTypes}
                helperText="Inventory lookup for the destination host."
              />
            </Box>
          ) : (
            <>
              <Box sx={{ mb: 2 }}>
                <TextField
                  {...register(DEST_HOST)}
                  label="Destination Host"
                  fullWidth
                  helperText="Manual host address for the destination database."
                />
              </Box>
              <Box sx={{ mb: 2 }}>
                <TextField
                  {...register(DEST_PORT)}
                  label="Destination Port"
                  type="number"
                  fullWidth
                  slotProps={{ htmlInput: { min: 1, max: 65535 } }}
                  helperText="Port of the destination database (1-65535)."
                />
              </Box>
            </>
          )}
        </Box>
      )}
    </Box>
  );
}

interface DestinationRenderConfig {
  destMode: DestMode;
  onDestModeChange: (mode: DestMode) => void;
  useDifferentHost: boolean;
  onUseDifferentHostChange: (value: boolean) => void;
  hostMode: HostMode;
  onHostModeChange: (mode: HostMode) => void;
}

/**
 * Build the per-field override that replaces the Source, Destination, and
 * Destination Host sections. Each section folds its wire fields onto a single
 * anchor field (the rest collapse to nothing via `false`), so the unified
 * combos and the explicit toggles render in place of the raw inputs. Every
 * other field defers to the framework default.
 */
function makeRenderField(
  mode: SourceMode,
  onModeChange: (mode: SourceMode) => void,
  dest: DestinationRenderConfig,
): (args: RenderFieldArgs) => ReactNode {
  const sourceAnchor = mode === 'schema' ? SOURCE_DB_ID : SOURCE_QUERY;
  return ({ field }: RenderFieldArgs) => {
    // Source section.
    if (SOURCE_FIELD_NAMES.has(field.name)) {
      if (field.name === sourceAnchor) {
        return <ArchiveSourceFields mode={mode} onModeChange={onModeChange} />;
      }
      // Folded into ArchiveSourceFields. Return `false` (not nullish) so the slot
      // renders nothing instead of falling back to the framework default widget;
      // the empty wrappers collapse to a single margin in normal block flow.
      return false;
    }

    // Destination section: anchor the whole block (toggle + relocated schema +
    // table, or the file input) on dest_table_id.
    if (field.name === DEST_TABLE_ID) {
      return <ArchiveDestinationFields mode={dest.destMode} onModeChange={dest.onDestModeChange} />;
    }
    if (DEST_FOLDED_FIELD_NAMES.has(field.name)) {
      return false;
    }

    // Destination Host section: anchor the opt-in block on dest_service_id.
    if (field.name === DEST_SERVICE_ID) {
      return (
        <ArchiveDestinationHostFields
          useDifferentHost={dest.useDifferentHost}
          onUseDifferentHostChange={dest.onUseDifferentHostChange}
          hostMode={dest.hostMode}
          onHostModeChange={dest.onHostModeChange}
          serviceTypes={
            ((field as { service_types?: string[] }).service_types ?? []) as readonly ServiceType[]
          }
        />
      );
    }
    if (DEST_HOST_FOLDED_FIELD_NAMES.has(field.name)) {
      return false;
    }

    return undefined;
  };
}

export interface ArchiveFormProps extends PluginFormSlotProps {
  submitLabel?: string;
}

/**
 * Whole-form slot for the archives create / edit pages. It composes the
 * framework {@link SchemaFormRenderer} unchanged except for the Source,
 * Destination, and Destination Host sections, which it overrides with unified
 * free-solo combos and explicit toggles. The framework still owns chrome,
 * mutation, snackbars, coercion, and the (unchanged) fail_when validators.
 */
export function ArchiveForm({
  sections,
  onSubmit,
  loading,
  defaultValues,
  capabilities,
  submitLabel,
}: ArchiveFormProps) {
  const [mode, setMode] = useState<SourceMode>(defaultValues?.[SOURCE_QUERY] ? 'query' : 'schema');
  const [destMode, setDestMode] = useState<DestMode>(defaultValues?.[DEST_FILE] ? 'file' : 'table');
  // UI-only opt-in: on when an edit prefill carries any destination host field.
  const [useDifferentHost, setUseDifferentHost] = useState<boolean>(
    Boolean(defaultValues?.[DEST_SERVICE_ID]) || Boolean(defaultValues?.[DEST_HOST]),
  );
  const [hostMode, setHostMode] = useState<HostMode>(
    defaultValues?.[DEST_HOST] ? 'manual' : 'service',
  );

  // The override depends only on the mode flags (the setters are stable), so
  // memoize the function itself rather than rebuilding it on every render.
  const renderField = useMemo(
    () =>
      makeRenderField(mode, setMode, {
        destMode,
        onDestModeChange: setDestMode,
        useDifferentHost,
        onUseDifferentHostChange: setUseDifferentHost,
        hostMode,
        onHostModeChange: setHostMode,
      }),
    [mode, destMode, useDifferentHost, hostMode],
  );

  return (
    <SchemaFormRenderer
      sections={sections}
      onSubmit={onSubmit}
      loading={loading}
      defaultValues={defaultValues}
      capabilities={capabilities}
      submitLabel={submitLabel}
      renderField={renderField}
    />
  );
}
