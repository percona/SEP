import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import type { ExecutionEvent } from '../../hooks/useExecutionEvents';

export interface ExecutionEventsPanelProps {
  eventsByStep: Record<string, ExecutionEvent[]>;
  activeStep: string | undefined;
  height?: number | string;
}

function eventLine(ev: ExecutionEvent): string {
  const step = ev.step ?? '';
  const prefix = step ? `${ev.type}[${step}]` : ev.type;
  return `${prefix} ${ev.description}`;
}

export function ExecutionEventsPanel({
  eventsByStep,
  activeStep,
  height = 400,
}: ExecutionEventsPanelProps) {
  const stepKeys = Object.keys(eventsByStep);
  if (stepKeys.length === 0) {
    return (
      <Box sx={{ p: 2, color: 'text.secondary' }}>
        <Typography variant="body2">No execution events yet.</Typography>
      </Box>
    );
  }

  const key = activeStep !== undefined && activeStep in eventsByStep ? activeStep : stepKeys[0];
  const list = eventsByStep[key] ?? [];

  if (list.length === 0) {
    return (
      <Box sx={{ p: 2, color: 'text.secondary' }}>
        <Typography variant="body2">No execution events for this step.</Typography>
      </Box>
    );
  }

  return (
    <Box
      component="ol"
      sx={{
        listStyle: 'none',
        m: 0,
        p: 1,
        height,
        overflow: 'auto',
        fontFamily: "'Roboto Mono', monospace",
        fontSize: '0.8rem',
      }}
    >
      {list.map((ev, idx) => (
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
  );
}
