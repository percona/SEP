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

import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import CircularProgress from '@mui/material/CircularProgress';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import {
  useSystemObservation,
  type SystemObservation,
  type SystemObservationEntity,
} from './hooks';

/**
 * Format an ISO timestamp for display, falling back to the raw value when it
 * is not a parseable date (mirrors the framework's ScheduledTaskRow helper).
 */
function formatObservedAt(value: string | null | undefined): string | null {
  if (!value) {
    return null;
  }
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
}

/**
 * Coerce an arbitrary upstream scalar to displayable text. The observation
 * fields are loosely typed (the sub-app owns their exact shape), so a number
 * or boolean is stringified and anything empty/nullish collapses to a dash —
 * never passing a non-primitive straight to a React child.
 */
function scalarText(value: unknown): string {
  if (value === null || value === undefined) {
    return '—';
  }
  if (typeof value === 'string') {
    return value.trim() ? value : '—';
  }
  if (typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  return '—';
}

function ScalarFact({ label, value }: { label: string; value: unknown }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body1">{scalarText(value)}</Typography>
    </Box>
  );
}

/**
 * Render an arbitrary JSON blob (installed_packages / config) defensively:
 * an empty or missing object collapses to a dash, anything else is
 * pretty-printed in a scrollable, monospace block so large payloads do not
 * blow out the layout.
 */
function JsonFact({ label, value }: { label: string; value: unknown }) {
  const isEmpty =
    value === null ||
    value === undefined ||
    (Array.isArray(value) && value.length === 0) ||
    (typeof value === 'object' &&
      !Array.isArray(value) &&
      Object.keys(value as object).length === 0);

  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      {isEmpty ? (
        <Typography variant="body1">—</Typography>
      ) : (
        <Box
          component="pre"
          sx={{
            m: 0,
            mt: 0.5,
            p: 1.5,
            maxHeight: 320,
            overflow: 'auto',
            borderRadius: 1,
            bgcolor: 'action.hover',
            fontFamily: 'monospace',
            fontSize: '0.8125rem',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {JSON.stringify(value, null, 2)}
        </Box>
      )}
    </Box>
  );
}

/**
 * System Facts section for an inventory node or service detail page.
 *
 * Displays the system observation collected by the syncer (OS version,
 * database engine version, installed packages, config) plus its
 * ``observed_at`` provenance timestamp. When nothing has been collected yet
 * the upstream returns 404, normalized to a graceful empty state by
 * ``useSystemObservation`` — never an error toast.
 */
export function SystemFactsPanel({
  entity,
  id,
}: {
  entity: SystemObservationEntity;
  id: string | number;
}) {
  const { data, isLoading, isError } = useSystemObservation(entity, id);

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="h6" sx={{ mb: 2 }}>
        System Facts
      </Typography>
      <Card variant="outlined">
        <CardContent>{renderBody({ entity, data, isLoading, isError })}</CardContent>
      </Card>
    </Box>
  );
}

function renderBody({
  entity,
  data,
  isLoading,
  isError,
}: {
  entity: SystemObservationEntity;
  data: SystemObservation | null | undefined;
  isLoading: boolean;
  isError: boolean;
}) {
  if (isLoading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
        <CircularProgress size={24} />
      </Box>
    );
  }

  if (isError) {
    return (
      <Typography variant="body2" color="error">
        Could not load system facts.
      </Typography>
    );
  }

  if (!data) {
    return (
      <Typography variant="body2" color="text.secondary">
        No system facts collected yet
      </Typography>
    );
  }

  const observedAt = formatObservedAt(data.observed_at);

  // Host and service observations carry disjoint field sets:
  // a node has os_version / installed_packages / config, a service has
  // db_engine_version. Render only the fields the entity actually owns so a
  // page never shows a field that can never be populated.
  return (
    <Stack spacing={2}>
      {entity === 'nodes' ? (
        <>
          <ScalarFact label="OS version" value={data.os_version} />
          <JsonFact label="Installed packages" value={data.installed_packages} />
          <JsonFact label="Config" value={data.config} />
        </>
      ) : (
        <ScalarFact label="Database engine version" value={data.db_engine_version} />
      )}
      {observedAt ? (
        <Typography variant="caption" color="text.secondary">
          Observed at {observedAt}
        </Typography>
      ) : null}
    </Stack>
  );
}
