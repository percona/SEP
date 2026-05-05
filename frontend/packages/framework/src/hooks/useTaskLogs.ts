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

import { useEffect, useRef, useState } from 'react';

export type LogType = 'stdout' | 'stderr';

export type StepText = Record<LogType, string>;

export type FinishStatus = 'success' | 'failed' | 'stopped' | 'lost';

export interface StreamError {
  code?: number;
  detail: unknown;
}

export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'finished' | 'error';

export interface TaskLogsState {
  textByStep: Record<string, StepText>;
  stepOrder: string[];
  streamStatus: StreamStatus;
  finishStatus?: FinishStatus;
  error?: StreamError;
}

interface IncomingLog {
  msg: string;
  step: string;
  type: LogType;
  offset: number;
}

/**
 * SSE-backed log stream for a task history.
 *
 * Single /stream-logs/{id} endpoint covers both running and completed tasks:
 * the server streams historical log lines then emits a `finish` event with
 * terminal status. No REST fallback needed.
 *
 * Cookie auth: EventSource cannot send Bearer headers. Same-origin SSE
 * endpoints remain cookie-authenticated during the Bearer-token migration.
 */
export function useTaskLogs(taskHistoryId: number | string | undefined): TaskLogsState {
  const [textByStep, setTextByStep] = useState<Record<string, StepText>>({});
  const [stepOrder, setStepOrder] = useState<string[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [finishStatus, setFinishStatus] = useState<FinishStatus | undefined>();
  const [error, setError] = useState<StreamError | undefined>();

  const offsetsRef = useRef<Record<string, number>>({});

  useEffect(() => {
    if (taskHistoryId === undefined || taskHistoryId === null || taskHistoryId === '') {
      return;
    }

    // Reset state on id change
    offsetsRef.current = {};
    setTextByStep({});
    setStepOrder([]);
    setFinishStatus(undefined);
    setError(undefined);
    setStreamStatus('connecting');

    const url = `/stream-logs/${encodeURIComponent(String(taskHistoryId))}`;
    const src = new EventSource(url, { withCredentials: true });

    src.onopen = () => setStreamStatus('streaming');

    src.onerror = () => {
      // EventSource auto-reconnects while readyState is CONNECTING.
      // Only surface a terminal error when the stream is permanently closed.
      if (src.readyState === EventSource.CLOSED) {
        setError({ detail: { message: 'Task log stream connection closed.' } });
        setStreamStatus('error');
      } else {
        setStreamStatus('connecting');
      }
    };

    src.onmessage = (event: MessageEvent<string>) => {
      let payload: IncomingLog;
      try {
        payload = JSON.parse(event.data) as IncomingLog;
      } catch {
        return;
      }
      const { msg, step, type, offset } = payload;
      if (typeof msg !== 'string' || !step || !type || typeof offset !== 'number') {
        return;
      }
      const key = `${step}_${type}`;
      const previousOffset = offsetsRef.current[key];
      if (previousOffset !== undefined && offset <= previousOffset) {
        return;
      }
      offsetsRef.current[key] = offset;

      setTextByStep((prev) => {
        const existing = prev[step] ?? { stdout: '', stderr: '' };
        return {
          ...prev,
          [step]: { ...existing, [type]: existing[type] + msg },
        };
      });
      setStepOrder((prev) => (prev.includes(step) ? prev : [...prev, step]));
    };

    const handleFinish = (event: MessageEvent<string>) => {
      try {
        const data = JSON.parse(event.data) as { status?: FinishStatus };
        if (data.status) {
          setFinishStatus(data.status);
        }
      } catch {
        // ignore malformed finish payload
      }
      setStreamStatus('finished');
      src.close();
    };

    const handleSepError = (event: MessageEvent<string>) => {
      let payload: StreamError;
      try {
        const parsed = JSON.parse(event.data) as { code?: number; detail?: unknown };
        payload = { code: parsed.code, detail: parsed.detail ?? event.data };
      } catch {
        payload = { detail: String(event.data || 'Unknown stream error') };
      }
      setError(payload);
      setStreamStatus('error');
      src.close();
    };

    src.addEventListener('finish', handleFinish as EventListener);
    src.addEventListener('sep-error', handleSepError as EventListener);

    return () => {
      src.removeEventListener('finish', handleFinish as EventListener);
      src.removeEventListener('sep-error', handleSepError as EventListener);
      src.close();
    };
  }, [taskHistoryId]);

  return { textByStep, stepOrder, streamStatus, finishStatus, error };
}
