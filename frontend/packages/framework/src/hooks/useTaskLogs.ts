import { useQuery } from '@tanstack/react-query';

interface LogLine {
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  message: string;
}

// TODO: connect to SSE endpoint for real-time log streaming
const MOCK_LOGS: LogLine[] = [
  { timestamp: '2025-01-15T10:00:01Z', level: 'info', message: 'Task started' },
  { timestamp: '2025-01-15T10:00:02Z', level: 'info', message: 'Connecting to database...' },
  { timestamp: '2025-01-15T10:00:03Z', level: 'info', message: 'Running checksum verification' },
  { timestamp: '2025-01-15T10:00:05Z', level: 'info', message: 'Task completed successfully' },
];

export function useTaskLogs(taskId: string | undefined) {
  return useQuery<LogLine[]>({
    queryKey: ['tasks', taskId, 'logs'],
    enabled: !!taskId,
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 300));
      return MOCK_LOGS;
    },
    placeholderData: [],
  });
}
