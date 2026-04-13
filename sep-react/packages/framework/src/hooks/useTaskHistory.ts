import { useQuery } from '@tanstack/react-query';

interface TaskHistoryEntry {
  id: string;
  status: string;
  startedAt: string;
  completedAt?: string;
  duration?: string;
  triggeredBy?: string;
}

// TODO: connect to real API
const MOCK_HISTORY: TaskHistoryEntry[] = [
  { id: 'run-001', status: 'completed', startedAt: '2025-01-15T10:00:00Z', completedAt: '2025-01-15T10:05:00Z', duration: '5m 0s', triggeredBy: 'admin' },
  { id: 'run-002', status: 'failed', startedAt: '2025-01-14T08:00:00Z', completedAt: '2025-01-14T08:01:30Z', duration: '1m 30s', triggeredBy: 'scheduler' },
  { id: 'run-003', status: 'completed', startedAt: '2025-01-13T12:00:00Z', completedAt: '2025-01-13T12:10:00Z', duration: '10m 0s', triggeredBy: 'admin' },
];

export function useTaskHistory(pluginName: string, taskId?: string) {
  return useQuery<TaskHistoryEntry[]>({
    queryKey: ['plugins', pluginName, 'tasks', taskId, 'history'],
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 300));
      return MOCK_HISTORY;
    },
    placeholderData: MOCK_HISTORY,
  });
}
