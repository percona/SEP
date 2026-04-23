import { useEffect, useRef, useState } from 'react';

export interface ExecutionEvent {
  timestamp: string;
  type: string;
  description: string;
  step?: string | null;
}

export interface ExecutionEventsState {
  events: ExecutionEvent[];
  eventsByStep: Record<string, ExecutionEvent[]>;
  stepOrder: string[];
  isLoading: boolean;
  error?: unknown;
}

const STEPLESS_KEY = '';

function compositeKey(ev: ExecutionEvent): string {
  return `${ev.timestamp ?? ''}|${ev.type ?? ''}|${ev.description ?? ''}|${ev.step ?? ''}`;
}

function groupByStep(events: ExecutionEvent[]): {
  eventsByStep: Record<string, ExecutionEvent[]>;
  stepOrder: string[];
} {
  const eventsByStep: Record<string, ExecutionEvent[]> = {};
  const stepOrder: string[] = [];
  for (const ev of events) {
    const step = ev.step ?? '';
    const key = step !== '' ? String(step) : STEPLESS_KEY;
    if (!eventsByStep[key]) {
      eventsByStep[key] = [];
      stepOrder.push(key);
    }
    eventsByStep[key].push(ev);
  }
  return { eventsByStep, stepOrder };
}

/**
 * Execution events for a task history.
 *
 * Running tasks stream via SSE /stream-logs/{id}/execution-events.
 * Completed tasks fetch REST /execution-events/{id}.
 *
 * Both endpoints are cookie-authenticated (same-origin). See useTaskLogs for
 * the auth rationale.
 */
export function useExecutionEvents(
  taskHistoryId: number | string | undefined,
  isRunning: boolean,
): ExecutionEventsState {
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<unknown>(undefined);

  const seenKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (taskHistoryId === undefined || taskHistoryId === null || taskHistoryId === '') {
      return;
    }

    seenKeysRef.current = new Set();
    setEvents([]);
    setError(undefined);
    setIsLoading(true);

    const idStr = encodeURIComponent(String(taskHistoryId));

    if (!isRunning) {
      const controller = new AbortController();
      fetch(`/execution-events/${idStr}`, {
        credentials: 'include',
        signal: controller.signal,
      })
        .then((res) => (res.ok ? (res.json() as Promise<ExecutionEvent[]>) : []))
        .then((data) => {
          const list = Array.isArray(data) ? data : [];
          for (const ev of list) {
            seenKeysRef.current.add(compositeKey(ev));
          }
          setEvents(list);
          setIsLoading(false);
        })
        .catch((err: unknown) => {
          if ((err as { name?: string } | null)?.name === 'AbortError') {
            return;
          }
          setError(err);
          setIsLoading(false);
        });
      return () => controller.abort();
    }

    const src = new EventSource(`/stream-logs/${idStr}/execution-events`, {
      withCredentials: true,
    });

    src.onerror = () => {
      if (src.readyState === EventSource.CLOSED) {
        setError({ message: 'Execution events stream connection closed.' });
        setIsLoading(false);
      }
      // Transient errors (readyState === CONNECTING) trigger browser auto-retry;
      // leave state unchanged.
    };

    src.onmessage = (event: MessageEvent<string>) => {
      let payload: ExecutionEvent;
      try {
        payload = JSON.parse(event.data) as ExecutionEvent;
      } catch {
        return;
      }
      const key = compositeKey(payload);
      if (seenKeysRef.current.has(key)) {
        return;
      }
      seenKeysRef.current.add(key);
      setEvents((prev) => [...prev, payload]);
      setIsLoading(false);
    };

    const handleFinish = () => {
      setIsLoading(false);
      src.close();
    };

    const handleSepError = (event: MessageEvent<string>) => {
      let payload: unknown = event.data;
      try {
        payload = JSON.parse(event.data);
      } catch {
        // keep raw
      }
      setError(payload);
      setIsLoading(false);
      src.close();
    };

    src.addEventListener('finish', handleFinish as EventListener);
    src.addEventListener('sep-error', handleSepError as EventListener);

    return () => {
      src.removeEventListener('finish', handleFinish as EventListener);
      src.removeEventListener('sep-error', handleSepError as EventListener);
      src.close();
    };
  }, [taskHistoryId, isRunning]);

  const { eventsByStep, stepOrder } = groupByStep(events);

  return { events, eventsByStep, stepOrder, isLoading, error };
}
