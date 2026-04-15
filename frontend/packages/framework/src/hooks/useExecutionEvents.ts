import { useQuery } from '@tanstack/react-query';

interface ExecutionEvent {
  id: string;
  type: 'started' | 'progress' | 'completed' | 'failed';
  timestamp: string;
  message: string;
  progress?: number;
}

// TODO: connect to SSE endpoint for real-time execution events
export function useExecutionEvents(taskId: string | undefined) {
  return useQuery<ExecutionEvent[]>({
    queryKey: ['tasks', taskId, 'events'],
    enabled: !!taskId,
    queryFn: async () => {
      await new Promise((r) => setTimeout(r, 200));
      return [
        {
          id: '1',
          type: 'started' as const,
          timestamp: new Date().toISOString(),
          message: 'Execution started',
        },
        {
          id: '2',
          type: 'completed' as const,
          timestamp: new Date().toISOString(),
          message: 'Execution completed',
        },
      ];
    },
    placeholderData: [],
  });
}
