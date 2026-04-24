import SearchIcon from '@mui/icons-material/Search';
import Box from '@mui/material/Box';
import InputAdornment from '@mui/material/InputAdornment';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { useMemo, useState } from 'react';
import type { ExecutionEvent } from '../../hooks/useExecutionEvents';

export const STEPLESS_STEP_KEY = '';
export const STEPLESS_STEP_LABEL = 'General';

export interface ExecutionEventsPanelProps {
  eventsByStep: Record<string, ExecutionEvent[]>;
  activeStep: string | undefined;
  height?: number | string;
}

function eventLine(ev: ExecutionEvent): string {
  const step = ev.step ?? '';
  const prefix = step !== '' ? `${ev.type}[${step}]` : ev.type;
  return `${prefix} ${ev.description}`;
}

function matchesQuery(ev: ExecutionEvent, needle: string): boolean {
  if (!needle) {
    return true;
  }
  const haystack = `${ev.timestamp ?? ''} ${eventLine(ev)}`.toLowerCase();
  return haystack.includes(needle);
}

export function ExecutionEventsPanel({
  eventsByStep,
  activeStep,
  height = 400,
}: ExecutionEventsPanelProps) {
  const [query, setQuery] = useState('');

  const stepKeys = Object.keys(eventsByStep);
  const resolvedKey =
    activeStep !== undefined && activeStep in eventsByStep ? activeStep : stepKeys[0];
  const list = resolvedKey !== undefined ? (eventsByStep[resolvedKey] ?? []) : [];

  const needle = query.trim().toLowerCase();
  const filtered = useMemo(() => list.filter((ev) => matchesQuery(ev, needle)), [list, needle]);

  if (stepKeys.length === 0) {
    return (
      <Box sx={{ p: 2, color: 'text.secondary' }}>
        <Typography variant="body2">No execution events yet.</Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height }}>
      <Box sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
        <TextField
          size="small"
          fullWidth
          placeholder="Search events"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <SearchIcon fontSize="small" />
                </InputAdornment>
              ),
            },
          }}
        />
      </Box>

      {list.length === 0 ? (
        <Box sx={{ p: 2, color: 'text.secondary' }}>
          <Typography variant="body2">No execution events for this step.</Typography>
        </Box>
      ) : filtered.length === 0 ? (
        <Box sx={{ p: 2, color: 'text.secondary' }}>
          <Typography variant="body2">No events match &ldquo;{query}&rdquo;.</Typography>
        </Box>
      ) : (
        <Box
          component="ol"
          sx={{
            listStyle: 'none',
            m: 0,
            p: 1,
            flex: 1,
            overflow: 'auto',
            fontFamily: "'Roboto Mono', monospace",
            fontSize: '0.8rem',
          }}
        >
          {filtered.map((ev, idx) => (
            <Box
              component="li"
              key={`${ev.timestamp}-${idx}`}
              sx={{ display: 'flex', gap: 1.5, py: 0.25 }}
            >
              <Box
                component="time"
                dateTime={ev.timestamp}
                sx={{ color: 'text.secondary', whiteSpace: 'nowrap' }}
              >
                {ev.timestamp}
              </Box>
              <Box sx={{ whiteSpace: 'pre-wrap' }}>{eventLine(ev)}</Box>
            </Box>
          ))}
        </Box>
      )}
    </Box>
  );
}
