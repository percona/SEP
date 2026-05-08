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

import { EventStreamContentType, fetchEventSource } from '@microsoft/fetch-event-source';
import { getToken, refreshAccessToken } from '@sep/api';
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

// Local sentinel class: thrown from onopen after a successful token refresh so
// that onerror can return 0 (immediate retry) with the new token.  We define
// it here rather than importing from fetch-event-source because version 2.0.1
// does not export RetriableError / FatalError.
class StreamRetriableAfterRefresh extends Error {}

/**
 * SSE-backed log stream for a task history.
 *
 * Single /stream-logs/{id} endpoint covers both running and completed tasks:
 * the server streams historical log lines then emits a `finish` event with
 * terminal status. No REST fallback needed.
 *
 * Uses @microsoft/fetch-event-source so the Bearer token can be attached as a
 * header — the browser EventSource API has no headers option and could only
 * carry cookies, which are not in scope for the SPA OAuth session.
 */
export function useTaskLogs(taskHistoryId: number | string | undefined): TaskLogsState {
  const [textByStep, setTextByStep] = useState<Record<string, StepText>>({});
  const [stepOrder, setStepOrder] = useState<string[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  const [finishStatus, setFinishStatus] = useState<FinishStatus | undefined>();
  const [error, setError] = useState<StreamError | undefined>();

  const offsetsRef = useRef<Record<string, number>>({});
  // Stable ref so onclose can read current streamStatus without re-registering.
  const streamStatusRef = useRef<StreamStatus>('idle');

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
    streamStatusRef.current = 'connecting';
    setStreamStatus('connecting');

    const ctrl = new AbortController();
    let currentToken = getToken() ?? '';
    let refreshAttempted = false;

    const url = `/stream-logs/${encodeURIComponent(String(taskHistoryId))}`;

    fetchEventSource(url, {
      signal: ctrl.signal,
      openWhenHidden: true,

      // Custom fetch so we can inject a fresh token on every (re)connect,
      // including after a 401-triggered refresh.
      fetch: (input, init) =>
        globalThis.fetch(input as RequestInfo, {
          ...init,
          headers: {
            ...init?.headers,
            Authorization: `Bearer ${currentToken}`,
          },
        }),

      onopen: async (response) => {
        if (response.ok && response.headers.get('content-type')?.includes(EventStreamContentType)) {
          streamStatusRef.current = 'streaming';
          setStreamStatus('streaming');
          return;
        }
        if (response.status === 401 && !refreshAttempted) {
          refreshAttempted = true;
          const newToken = await refreshAccessToken();
          if (newToken) {
            currentToken = newToken;
            // Throw our local sentinel so onerror can return 0 (immediate retry)
            // with the updated token — without confusing it for a generic error.
            throw new StreamRetriableAfterRefresh();
          }
        }
        throw new Error(`Stream open failed with status ${response.status}`);
      },

      onmessage: (ev) => {
        if (ev.data === '') {
          return; // keepalive comment line
        }

        if (ev.event === 'finish') {
          try {
            const data = JSON.parse(ev.data) as { status?: FinishStatus };
            if (data.status) {
              setFinishStatus(data.status);
            }
          } catch {
            // ignore malformed finish payload
          }
          streamStatusRef.current = 'finished';
          setStreamStatus('finished');
          ctrl.abort();
          return;
        }

        if (ev.event === 'sep-error') {
          let payload: StreamError;
          try {
            const parsed = JSON.parse(ev.data) as { code?: number; detail?: unknown };
            payload = { code: parsed.code, detail: parsed.detail ?? ev.data };
          } catch {
            payload = { detail: String(ev.data || 'Unknown stream error') };
          }
          setError(payload);
          streamStatusRef.current = 'error';
          setStreamStatus('error');
          ctrl.abort();
          return;
        }

        // Default message event — log line
        let payload: IncomingLog;
        try {
          payload = JSON.parse(ev.data) as IncomingLog;
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
      },

      onerror: (err): number | undefined => {
        if (err instanceof StreamRetriableAfterRefresh) {
          // Immediate retry: token was just refreshed, no need to back off.
          return 0;
        }
        // All other errors (transient network blips, wrong content-type, etc.)
        // surface as 'connecting' and let fetchEventSource retry with backoff.
        streamStatusRef.current = 'connecting';
        setStreamStatus('connecting');
        return undefined; // library retries after default 1 000 ms backoff
      },

      onclose: () => {
        // Server closed the connection cleanly without a finish/sep-error frame.
        // Surface as a terminal error only if we haven't already reached a
        // finished/error state (abort() from onmessage arrives after onclose).
        const s = streamStatusRef.current;
        if (s !== 'finished' && s !== 'error') {
          setError({ detail: { message: 'Task log stream connection closed.' } });
          streamStatusRef.current = 'error';
          setStreamStatus('error');
        }
      },
    }).catch(() => {
      // fetchEventSource rejects when AbortController fires — expected on
      // unmount / id change. Only surface unexpected rejections.
    });

    return () => ctrl.abort();
  }, [taskHistoryId]);

  return { textByStep, stepOrder, streamStatus, finishStatus, error };
}
