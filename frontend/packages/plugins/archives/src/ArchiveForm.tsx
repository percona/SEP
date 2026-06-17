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
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import {
  SchemaFormRenderer,
  useSchemas,
  useTables,
  type PluginFormSlotProps,
  type RenderFieldArgs,
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

/**
 * Build the per-field override that replaces the Source section. The five source
 * wire fields are folded into {@link ArchiveSourceFields}: it renders on the
 * anchor field that is visible in the active mode (`source_db_id` for schema,
 * `source_query` for query), and the rest collapse to nothing. Every other
 * field defers to the framework default.
 */
function makeRenderField(
  mode: SourceMode,
  onModeChange: (mode: SourceMode) => void,
): (args: RenderFieldArgs) => ReactNode {
  const anchor = mode === 'schema' ? SOURCE_DB_ID : SOURCE_QUERY;
  return ({ field }: RenderFieldArgs) => {
    if (!SOURCE_FIELD_NAMES.has(field.name)) {
      return undefined;
    }
    if (field.name === anchor) {
      return <ArchiveSourceFields mode={mode} onModeChange={onModeChange} />;
    }
    // Folded into ArchiveSourceFields. Return `false` (not nullish) so the slot
    // renders nothing instead of falling back to the framework default widget;
    // the empty wrappers collapse to a single margin in normal block flow.
    return false;
  };
}

export interface ArchiveFormProps extends PluginFormSlotProps {
  submitLabel?: string;
}

/**
 * Whole-form slot for the archives create / edit pages. It composes the
 * framework {@link SchemaFormRenderer} unchanged except for the Source section,
 * which it overrides with a unified free-solo schema / table combo and an
 * explicit mode toggle. The framework still owns chrome, mutation, snackbars,
 * coercion, and the (unchanged) fail_when validators.
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

  // The override only depends on `mode` (setMode is stable), so memoize the
  // function itself rather than rebuilding it on every per-field render.
  const renderField = useMemo(() => makeRenderField(mode, setMode), [mode]);

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
