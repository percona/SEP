import Box from '@mui/material/Box';
import Typography from '@mui/material/Typography';
import Paper from '@mui/material/Paper';

interface LogLine {
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  message: string;
}

interface TaskLogViewerProps {
  taskId: string;
  logs?: LogLine[];
  isLoading?: boolean;
}

const LEVEL_COLORS: Record<string, string> = {
  info: 'text.primary',
  warn: 'warning.main',
  error: 'error.main',
  debug: 'text.secondary',
};

// TODO: connect to SSE endpoint for real-time logs
export function TaskLogViewer({ taskId, logs = [], isLoading }: TaskLogViewerProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        bgcolor: 'grey.900',
        color: 'grey.100',
        fontFamily: "'Roboto Mono', monospace",
        fontSize: '0.8rem',
        maxHeight: 400,
        overflow: 'auto',
      }}
    >
      {isLoading && (
        <Typography variant="body2" color="grey.500">
          Connecting to log stream...
        </Typography>
      )}
      {logs.length === 0 && !isLoading && (
        <Typography variant="body2" color="grey.500">
          No log output available for task {taskId}.
        </Typography>
      )}
      {logs.map((line, i) => (
        <Box key={i} sx={{ py: 0.25 }}>
          <Typography
            component="span"
            variant="body2"
            sx={{ fontFamily: 'inherit', fontSize: 'inherit', color: 'grey.500', mr: 1 }}
          >
            {line.timestamp}
          </Typography>
          <Typography
            component="span"
            variant="body2"
            sx={{
              fontFamily: 'inherit',
              fontSize: 'inherit',
              color: LEVEL_COLORS[line.level],
              mr: 1,
            }}
          >
            [{line.level.toUpperCase()}]
          </Typography>
          <Typography
            component="span"
            variant="body2"
            sx={{ fontFamily: 'inherit', fontSize: 'inherit' }}
          >
            {line.message}
          </Typography>
        </Box>
      ))}
    </Paper>
  );
}
