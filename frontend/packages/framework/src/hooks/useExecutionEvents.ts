import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useRef, useState } from 'react';

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

async function fetchExecutionEvents(taskHistoryId: string): Promise<ExecutionEvent[]> {
  const res = await fetch(`/execution-events/${taskHistoryId}`, { credentials: 'include' });
  if (!res.ok) {
    throw new Error(`Execution events request failed with status ${res.status}`);
  }
  const data = (await res.json()) as unknown;
  return Array.isArray(data) ? (data as ExecutionEvent[]) : [];
}

/**
 * Execution events for a task history.
 *
 * Running tasks stream via SSE /stream-logs/{id}/execution-events.
 * Completed tasks fetch REST /execution-events/{id} through react-query for
 * consistent error/loading/cache semantics with the rest of @sep/framework.
 *
 * Both endpoints are cookie-authenticated (same-origin). See useTaskLogs for
 * the auth rationale.
 */
export function useExecutionEvents(
  taskHistoryId: number | string | undefined,
  isRunning: boolean,
): ExecutionEventsState {
  const idStr =
    taskHistoryId === undefined || taskHistoryId === null || taskHistoryId === ''
      ? undefined
      : encodeURIComponent(String(taskHistoryId));

  // ── Completed tasks: REST via react-query ─────────────────────────────
  const query = useQuery<ExecutionEvent[]>({
    queryKey: ['execution-events', idStr],
    queryFn: () => fetchExecutionEvents(idStr as string),
    enabled: !isRunning && idStr !== undefined,
  });

  // ── Running tasks: SSE ────────────────────────────────────────────────
  const [sseEvents, setSseEvents] = useState<ExecutionEvent[]>([]);
  const [sseError, setSseError] = useState<unknown>(undefined);
  const [sseLoading, setSseLoading] = useState(false);

  const seenKeysRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!isRunning || idStr === undefined) {
      return;
    }

    seenKeysRef.current = new Set();
    setSseEvents([]);
    setSseError(undefined);
    setSseLoading(true);

    const src = new EventSource(`/stream-logs/${idStr}/execution-events`, {
      withCredentials: true,
    });

    src.onerror = () => {
      if (src.readyState === EventSource.CLOSED) {
        setSseError({ message: 'Execution events stream connection closed.' });
        setSseLoading(false);
      }
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
      setSseEvents((prev) => [...prev, payload]);
      setSseLoading(false);
    };

    const handleFinish = () => {
      setSseLoading(false);
      src.close();
    };

    const handleSepError = (event: MessageEvent<string>) => {
      let payload: unknown = event.data;
      try {
        payload = JSON.parse(event.data);
      } catch {
        // keep raw
      }
      setSseError(payload);
      setSseLoading(false);
      src.close();
    };

    src.addEventListener('finish', handleFinish as EventListener);
    src.addEventListener('sep-error', handleSepError as EventListener);

    return () => {
      src.removeEventListener('finish', handleFinish as EventListener);
      src.removeEventListener('sep-error', handleSepError as EventListener);
      src.close();
    };
  }, [idStr, isRunning]);

  const events = isRunning ? sseEvents : (query.data ?? []);
  const error = isRunning ? sseError : (query.error ?? undefined);
  const isLoading = isRunning ? sseLoading : query.isLoading;

  const { eventsByStep, stepOrder } = useMemo(() => groupByStep(events), [events]);

  return { events, eventsByStep, stepOrder, isLoading, error };
}
